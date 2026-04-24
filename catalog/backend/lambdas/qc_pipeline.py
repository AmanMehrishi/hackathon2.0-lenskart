"""
QC Pipeline Lambda — Multi-Agent Orchestrator.

Receives:  {"sku_id", "s3_image_url", "product"}
Runs three concurrent Bedrock Converse sub-agents (Visual, Commercial, Semantic),
handles toolUse loops, feeds results to a Judge Agent, and updates DynamoDB.

Environment variables:
    DYNAMODB_TABLE     – CatalogQCTable
    S3_BUCKET          – image bucket (for Rekognition)
    BEDROCK_FAST_MODEL – Haiku for sub-agents (speed)
    BEDROCK_SMART_MODEL– Sonnet for Judge (reasoning)
    AWS_REGION_NAME    – defaults to us-east-1
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import boto3
from botocore.exceptions import ClientError

# Ensure tools/ is importable when deployed as a Lambda layer / flat package
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from tools.rekognition_tool import analyze_image_technical_specs
from tools.web_search_tool import search_live_pricing

logger = logging.getLogger()
logger.setLevel(logging.INFO)

DYNAMODB_TABLE = os.environ.get("DYNAMODB_TABLE", "CatalogQCTable")
BEDROCK_FAST_MODEL = os.environ.get(
    "BEDROCK_FAST_MODEL", "us.anthropic.claude-haiku-4-5-20251001-v1:0"
)
BEDROCK_SMART_MODEL = os.environ.get(
    "BEDROCK_SMART_MODEL", "us.anthropic.claude-sonnet-4-6"
)
REGION = os.environ.get("AWS_REGION_NAME", "us-east-1")

bedrock = boto3.client("bedrock-runtime", region_name=REGION)
dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(DYNAMODB_TABLE)


# ═══════════════════════════════════════════════════════════════════
#  Tool configs for Bedrock Converse API (toolConfig schemas)
# ═══════════════════════════════════════════════════════════════════

VISUAL_TOOL_CONFIG = {
    "tools": [
        {
            "toolSpec": {
                "name": "analyze_image_technical_specs",
                "description": (
                    "Analyze a product image using Amazon Rekognition. "
                    "Returns detected labels with bounding boxes, content moderation flags, "
                    "face count, and image quality metrics. Use this to validate the product "
                    "image is authentic, high-quality, and contains no unsafe content."
                ),
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "s3_image_url": {
                                "type": "string",
                                "description": "S3 URI of the product image (s3://bucket/key)",
                            },
                            "product_name": {
                                "type": "string",
                                "description": "Name of the product being inspected",
                            },
                            "category": {
                                "type": "string",
                                "description": "Product category for context",
                            },
                        },
                        "required": ["s3_image_url"],
                    }
                },
            }
        }
    ]
}

COMMERCIAL_TOOL_CONFIG = {
    "tools": [
        {
            "toolSpec": {
                "name": "search_live_pricing",
                "description": (
                    "Search the live web for current market pricing and fashion trend data "
                    "for a product. Returns real search results, extracted price points, "
                    "price comparison analysis, and trend signals. Use this to determine if "
                    "the proposed price is reasonable and the product is on-trend."
                ),
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "product_name": {
                                "type": "string",
                                "description": "Product name to search for",
                            },
                            "category": {
                                "type": "string",
                                "description": "Product category",
                            },
                            "proposed_price": {
                                "type": "number",
                                "description": "The seller's proposed price to compare against market",
                            },
                        },
                        "required": ["product_name"],
                    }
                },
            }
        }
    ]
}


# ═══════════════════════════════════════════════════════════════════
#  Tool dispatch — maps tool names to real Python functions
# ═══════════════════════════════════════════════════════════════════

TOOL_DISPATCH: dict[str, callable] = {
    "analyze_image_technical_specs": analyze_image_technical_specs,
    "search_live_pricing": search_live_pricing,
}


def execute_tool(tool_name: str, tool_input: dict) -> str:
    """Execute a real tool and return its JSON result string."""
    fn = TOOL_DISPATCH.get(tool_name)
    if fn is None:
        return json.dumps({"error": f"Unknown tool: {tool_name}"})
    try:
        logger.info("Executing tool '%s' with input: %s", tool_name, json.dumps(tool_input)[:500])
        result = fn(**tool_input)
        logger.info("Tool '%s' completed successfully", tool_name)
        return json.dumps(result, default=str)
    except Exception as e:
        logger.error("Tool '%s' execution failed: %s", tool_name, e, exc_info=True)
        return json.dumps({"error": str(e)})


# ═══════════════════════════════════════════════════════════════════
#  Bedrock Converse helpers
# ═══════════════════════════════════════════════════════════════════

def _converse(
    system_prompt: str,
    messages: list[dict],
    tool_config: dict | None = None,
    max_tokens: int = 4096,
    model_id: str | None = None,
) -> dict:
    """Single Bedrock Converse API call."""
    resolved_model = model_id or BEDROCK_FAST_MODEL
    kwargs: dict[str, Any] = {
        "modelId": resolved_model,
        "system": [{"text": system_prompt}],
        "messages": messages,
        "inferenceConfig": {
            "maxTokens": max_tokens,
            "temperature": 0.2,
        },
    }
    if tool_config:
        kwargs["toolConfig"] = tool_config

    logger.info("Calling Bedrock Converse (model=%s, messages=%d, has_tools=%s)",
                resolved_model, len(messages), tool_config is not None)
    response = bedrock.converse(**kwargs)
    return response


def _extract_text(response: dict) -> str:
    """Pull concatenated text from a Converse response."""
    parts = []
    for block in response.get("output", {}).get("message", {}).get("content", []):
        if "text" in block:
            parts.append(block["text"])
    return "\n".join(parts)


def _extract_tool_use(response: dict) -> list[dict]:
    """Pull all toolUse blocks from a Converse response."""
    uses = []
    for block in response.get("output", {}).get("message", {}).get("content", []):
        if "toolUse" in block:
            uses.append(block["toolUse"])
    return uses


def _get_stop_reason(response: dict) -> str:
    return response.get("stopReason", "")


# ═══════════════════════════════════════════════════════════════════
#  Sub-Agent runners (each handles a full toolUse loop)
# ═══════════════════════════════════════════════════════════════════

MAX_TOOL_ROUNDS = 3


async def run_visual_agent(s3_image_url: str, product: dict) -> dict:
    """
    Visual Agent — image validation & authenticity.
    Has access to analyze_image_technical_specs (Rekognition).
    """
    system_prompt = (
        "You are a technical image inspector and fraud detector for an EYEWEAR e-commerce catalog "
        "(spectacles, sunglasses, eye frames, reading glasses, and optical accessories ONLY).\n\n"
        "CRITICAL RULE: If the product in the image is NOT eyewear, immediately set recommendation "
        'to "FAIL" and include the issue: "Item is not eyewear."\n\n'
        "Your job is to analyze a product image and determine:\n"
        "1. Whether the image is high-quality enough for an e-commerce listing (sharp, well-lit, product visible).\n"
        "2. Whether the image contains any unsafe or inappropriate content.\n"
        "3. Whether the detected objects in the image match the claimed product category.\n"
        "4. Whether there are signs of image manipulation or stock photo misuse.\n"
        "5. Whether the product is actually eyewear (spectacles, sunglasses, eye frames).\n\n"
        "You MUST call the analyze_image_technical_specs tool to inspect the image. "
        "After receiving the tool results, produce your final report as a JSON object with these fields:\n"
        '{"image_quality_score": 1-10, "is_safe": true/false, "category_match": true/false, '
        '"is_eyewear": true/false, "detected_objects": ["list"], "issues": ["list of issues found"], '
        '"recommendation": "PASS" or "FAIL" or "REVIEW"}'
    )

    user_msg = (
        f"Analyze this product image for our catalog QC process.\n"
        f"Product: {product.get('product_name', 'Unknown')}\n"
        f"Category: {product.get('category', 'Unknown')}\n"
        f"S3 Image URL: {s3_image_url}\n\n"
        f"Call the tool to inspect the image, then give me your JSON report."
    )

    messages = [{"role": "user", "content": [{"text": user_msg}]}]

    logger.info("[Visual Agent] START — invoking Bedrock with Rekognition tool")
    for round_num in range(MAX_TOOL_ROUNDS):
        response = await asyncio.to_thread(
            _converse, system_prompt, messages, VISUAL_TOOL_CONFIG
        )
        stop_reason = _get_stop_reason(response)
        assistant_message = response["output"]["message"]
        messages.append(assistant_message)

        if stop_reason == "tool_use":
            tool_uses = _extract_tool_use(response)
            tool_result_blocks = []
            for tu in tool_uses:
                logger.info("[Visual Agent] toolUse round=%d, tool=%s", round_num + 1, tu["toolUseId"])
                result_str = execute_tool(tu["name"], tu["input"])
                tool_result_blocks.append({
                    "toolResult": {
                        "toolUseId": tu["toolUseId"],
                        "content": [{"json": json.loads(result_str)}],
                    }
                })
            messages.append({"role": "user", "content": tool_result_blocks})
        else:
            break

    final_text = _extract_text(response)
    logger.info("[Visual Agent] DONE — report length: %d chars", len(final_text))
    return {"agent": "visual", "report": final_text}


async def run_commercial_agent(product: dict) -> dict:
    """
    Commercial Agent — pricing sanity & fashion score.
    Has access to search_live_pricing (DuckDuckGo web search).
    """
    system_prompt = (
        "You are a pricing analyst and fashion trend forecaster for an EYEWEAR e-commerce catalog "
        "(spectacles, sunglasses, eye frames, reading glasses, and optical accessories ONLY).\n\n"
        "CRITICAL RULE: If the product is NOT eyewear, immediately set recommendation to \"FAIL\" "
        "and include the issue: \"Item is not eyewear — pricing analysis not applicable.\"\n\n"
        "Your job is to:\n"
        "1. Search for the product's current market price and compare it to the proposed price.\n"
        "2. Determine if the proposed price is reasonable, overpriced, or suspiciously cheap.\n"
        "3. Assess the product's fashion trendiness / market demand in the eyewear industry.\n"
        "4. Assign a fashion_score from 1-10.\n\n"
        "You MUST call the search_live_pricing tool to get real market data. "
        "After receiving the tool results, produce your final report as a JSON object with these fields:\n"
        '{"proposed_price": number, "average_market_price": number, '
        '"price_assessment": "REASONABLE" or "OVERPRICED" or "UNDERPRICED", '
        '"fashion_score": 1-10, "trend_signals": ["list"], '
        '"issues": ["list of pricing/trend concerns"], '
        '"recommendation": "PASS" or "FAIL" or "REVIEW"}'
    )

    user_msg = (
        f"Analyze the pricing and trendiness for this product:\n"
        f"Product: {product.get('product_name', 'Unknown')}\n"
        f"Category: {product.get('category', 'Unknown')}\n"
        f"Brand: {product.get('brand', 'Unknown')}\n"
        f"Proposed Price: ${product.get('proposed_price', 0)}\n\n"
        f"Call the tool to search the web, then give me your JSON report."
    )

    messages = [{"role": "user", "content": [{"text": user_msg}]}]

    logger.info("[Commercial Agent] START — invoking Bedrock with web search tool")
    for round_num in range(MAX_TOOL_ROUNDS):
        response = await asyncio.to_thread(
            _converse, system_prompt, messages, COMMERCIAL_TOOL_CONFIG
        )
        stop_reason = _get_stop_reason(response)
        assistant_message = response["output"]["message"]
        messages.append(assistant_message)

        if stop_reason == "tool_use":
            tool_uses = _extract_tool_use(response)
            tool_result_blocks = []
            for tu in tool_uses:
                logger.info("[Commercial Agent] toolUse round=%d, tool=%s", round_num + 1, tu["toolUseId"])
                result_str = execute_tool(tu["name"], tu["input"])
                tool_result_blocks.append({
                    "toolResult": {
                        "toolUseId": tu["toolUseId"],
                        "content": [{"json": json.loads(result_str)}],
                    }
                })
            messages.append({"role": "user", "content": tool_result_blocks})
        else:
            break

    final_text = _extract_text(response)
    logger.info("[Commercial Agent] DONE — report length: %d chars", len(final_text))
    return {"agent": "commercial", "report": final_text}


async def run_semantic_agent(s3_image_url: str, product: dict) -> dict:
    """
    Semantic Agent — classification audit & attribute completeness.
    No tools — pure LLM reasoning over the product metadata vs. image description.
    The image is passed directly to the model via Bedrock's image content block.
    """
    system_prompt = (
        "You are a catalog taxonomist and data quality auditor for an EYEWEAR e-commerce platform "
        "(spectacles, sunglasses, eye frames, reading glasses, and optical accessories ONLY).\n\n"
        "CRITICAL RULE: If the image does NOT show eyewear, immediately set recommendation to \"FAIL\" "
        "and include the issue: \"Item is not eyewear.\"\n\n"
        "You will receive a product image along with its metadata (name, category, attributes). "
        "Your job is to:\n"
        "1. Describe what you actually see in the image.\n"
        "2. Confirm the product is eyewear (spectacles, sunglasses, eye frames, etc.).\n"
        "3. Compare your visual description against the provided metadata.\n"
        "4. Identify any MISSING attributes that should be listed (e.g. frame color, lens type, material, size, shape).\n"
        "5. Identify any MISMATCHED attributes (metadata says 'blue' but image shows red).\n"
        "6. Verify the category classification is correct for an eyewear catalog.\n\n"
        "Produce your final report as a JSON object with these fields:\n"
        '{"image_description": "what you see", "is_eyewear": true/false, "category_correct": true/false, '
        '"missing_attributes": ["list"], "mismatched_attributes": ["list with explanations"], '
        '"attribute_completeness_score": 1-10, '
        '"issues": ["list of data quality issues"], '
        '"recommendation": "PASS" or "FAIL" or "REVIEW"}'
    )

    # Build multimodal content: image from S3 + text metadata
    s3_bucket, s3_key = s3_image_url.replace("s3://", "").split("/", 1)
    s3_client = boto3.client("s3", region_name=REGION)

    try:
        img_obj = await asyncio.to_thread(
            s3_client.get_object, Bucket=s3_bucket, Key=s3_key
        )
        image_bytes = img_obj["Body"].read()
        content_type = img_obj.get("ContentType", "image/jpeg")

        format_map = {
            "image/jpeg": "jpeg",
            "image/png": "png",
            "image/webp": "webp",
            "image/gif": "gif",
        }
        img_format = format_map.get(content_type, "jpeg")

        user_content = [
            {
                "image": {
                    "format": img_format,
                    "source": {"bytes": image_bytes},
                }
            },
            {
                "text": (
                    f"Here is the product image and its submitted metadata. "
                    f"Audit them for quality.\n\n"
                    f"Product Name: {product.get('product_name', 'N/A')}\n"
                    f"Category: {product.get('category', 'N/A')}\n"
                    f"Brand: {product.get('brand', 'N/A')}\n"
                    f"Proposed Price: ${product.get('proposed_price', 'N/A')}\n"
                    f"Attributes: {json.dumps(product.get('attributes', {}), indent=2)}\n\n"
                    f"Give me your JSON report."
                ),
            },
        ]
    except Exception as e:
        logger.warning("Could not load image from S3 for Semantic Agent, falling back to text-only: %s", e)
        user_content = [
            {
                "text": (
                    f"Audit this product's metadata for completeness and consistency. "
                    f"(Image could not be loaded: {e})\n\n"
                    f"Product Name: {product.get('product_name', 'N/A')}\n"
                    f"Category: {product.get('category', 'N/A')}\n"
                    f"Brand: {product.get('brand', 'N/A')}\n"
                    f"Proposed Price: ${product.get('proposed_price', 'N/A')}\n"
                    f"Attributes: {json.dumps(product.get('attributes', {}), indent=2)}\n\n"
                    f"Give me your JSON report."
                ),
            },
        ]

    messages = [{"role": "user", "content": user_content}]

    logger.info("[Semantic Agent] START — invoking Bedrock with multimodal image+text (no tools)")
    response = await asyncio.to_thread(
        _converse, system_prompt, messages, None
    )

    final_text = _extract_text(response)
    logger.info("[Semantic Agent] DONE — report length: %d chars", len(final_text))
    return {"agent": "semantic", "report": final_text}


# ═══════════════════════════════════════════════════════════════════
#  Judge Agent
# ═══════════════════════════════════════════════════════════════════

async def run_judge_agent(
    visual_report: str,
    commercial_report: str,
    semantic_report: str,
    product: dict,
) -> dict:
    """
    Judge Agent — combines the three sub-agent reports and renders a final verdict.
    Outputs strict JSON matching the DynamoDB update schema.
    """
    system_prompt = (
        "You are the final Quality Control judge for an EYEWEAR e-commerce catalog "
        "(spectacles, sunglasses, eye frames, reading glasses, and optical accessories ONLY).\n\n"
        "You will receive three independent QC reports from specialized agents:\n"
        "1. Visual Agent: image quality, safety, authenticity\n"
        "2. Commercial Agent: pricing analysis, fashion trends\n"
        "3. Semantic Agent: metadata completeness, category accuracy\n\n"
        "CONFIDENCE-BASED THRESHOLDS — you MUST grade your own confidence (0-100):\n"
        "- confidence_score >= 90 AND product clearly meets criteria → APPROVED\n"
        "- confidence_score >= 90 AND product severely violates criteria (e.g. not eyewear, NSFW) → REJECTED\n"
        "- confidence_score 50-89, OR sub-agents conflict with each other → FLAGGED_FOR_REVIEW\n"
        "- confidence_score < 50 → FLAGGED_FOR_REVIEW (insufficient data)\n\n"
        "EVALUATION RULES (strictly follow these to avoid over-flagging):\n"
        "1. ATTRIBUTE COMPLETENESS: The ONLY required fields are Product Name, Brand, Price, and Category. "
        "An empty 'attributes' object is 100% acceptable. Do NOT flag for missing UV protection, "
        "frame materials, lens type, size specs, or any optional attributes.\n"
        "2. PRICING SANITY: Only flag mathematically absurd prices: below $1 or above $10,000. "
        "Standard prices ($20-$500) are normal for eyewear. Do NOT flag standard discount prices "
        "(e.g. a $90 Ray-Ban) for 'authenticity concerns' or 'suspiciously low price.'\n"
        "3. PRODUCT NAME WEIGHTING: Give EXTREMELY LOW weight to the product name field. "
        "Names are creative and abstract (e.g. pink glasses named 'Panthers', sunglasses named 'Maverick'). "
        "NEVER penalize or flag a product for having an abstract, creative, or unconventional name.\n"
        "4. CATEGORY MATCHING: Give MAXIMUM weight to the Category field. The image must actually "
        "depict eyewear matching the claimed category. If the image shows a toaster but category "
        "says 'Sunglasses', REJECT.\n"
        "5. NON-EYEWEAR: If ANY agent reports the item is NOT eyewear → REJECTED.\n"
        "6. SAFETY: If ANY agent found NSFW/unsafe content → REJECTED.\n\n"
        "You MUST output ONLY a raw JSON object (no markdown, no explanation outside JSON) "
        "with EXACTLY this schema:\n"
        "{\n"
        '  "qc_status": "APPROVED" | "REJECTED" | "FLAGGED_FOR_REVIEW",\n'
        '  "confidence_score": <integer 0-100>,\n'
        '  "fashion_score": <integer 1-10 from the Commercial Agent>,\n'
        '  "reasoning": ["Clear reason 1", "Clear reason 2"]\n'
        "}\n\n"
        "reasoning should explain WHY you chose that status. Keep each reason to 1 sentence.\n"
        "If APPROVED, reasoning should briefly confirm what passed (e.g. [\"Image is valid eyewear\", \"Price is reasonable\"])."
    )

    user_msg = (
        f"Product: {product.get('product_name', 'Unknown')} | "
        f"Category: {product.get('category', 'Unknown')} | "
        f"Price: ${product.get('proposed_price', 0)}\n\n"
        f"=== VISUAL AGENT REPORT ===\n{visual_report}\n\n"
        f"=== COMMERCIAL AGENT REPORT ===\n{commercial_report}\n\n"
        f"=== SEMANTIC AGENT REPORT ===\n{semantic_report}\n\n"
        f"Render your final JSON verdict now."
    )

    messages = [{"role": "user", "content": [{"text": user_msg}]}]

    logger.info("[Judge Agent] START — invoking Bedrock with SMART model (%s)", BEDROCK_SMART_MODEL)
    response = await asyncio.to_thread(
        _converse, system_prompt, messages, None, 1024, BEDROCK_SMART_MODEL
    )

    raw = _extract_text(response)
    logger.info("[Judge Agent] Raw output: %s", raw[:1000])
    return _parse_judge_output(raw)


def _parse_judge_output(raw: str) -> dict:
    """Extract the JSON verdict from the Judge's response, tolerating markdown fences."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()

    try:
        verdict = json.loads(text)
    except json.JSONDecodeError:
        import re
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                verdict = json.loads(match.group())
            except json.JSONDecodeError:
                logger.error("Judge output is not valid JSON: %s", text[:500])
                verdict = {
                    "qc_status": "FLAGGED_FOR_REVIEW",
                    "confidence_score": 0,
                    "reasoning": ["Judge agent produced unparseable output — flagging for manual review"],
                    "fashion_score": 5,
                }
        else:
            logger.error("No JSON found in Judge output: %s", text[:500])
            verdict = {
                "qc_status": "FLAGGED_FOR_REVIEW",
                "confidence_score": 0,
                "reasoning": ["Judge agent produced no JSON — flagging for manual review"],
                "fashion_score": 5,
            }

    valid_statuses = {"APPROVED", "REJECTED", "FLAGGED_FOR_REVIEW"}
    if verdict.get("qc_status") not in valid_statuses:
        verdict["qc_status"] = "FLAGGED_FOR_REVIEW"
    if not isinstance(verdict.get("confidence_score"), (int, float)):
        verdict["confidence_score"] = 50
    verdict["confidence_score"] = max(0, min(100, int(verdict["confidence_score"])))
    if not isinstance(verdict.get("fashion_score"), (int, float)):
        verdict["fashion_score"] = 5
    if not isinstance(verdict.get("reasoning"), list):
        flags = verdict.get("qc_flags", [])
        verdict["reasoning"] = flags if isinstance(flags, list) else []
    verdict["qc_flags"] = verdict["reasoning"]

    return verdict


# ═══════════════════════════════════════════════════════════════════
#  DynamoDB update
# ═══════════════════════════════════════════════════════════════════

def update_qc_result(sku_id: str, verdict: dict) -> None:
    """Update the CatalogQCTable item with the Judge's verdict."""
    logger.info("[DynamoDB] Updating sku_id=%s with qc_status=%s, confidence=%s, fashion=%s",
                sku_id, verdict["qc_status"], verdict.get("confidence_score"), verdict.get("fashion_score"))
    try:
        table.update_item(
            Key={"sku_id": sku_id},
            UpdateExpression=(
                "SET qc_status = :status, "
                "qc_flags = :flags, "
                "fashion_score = :score, "
                "confidence_score = :confidence, "
                "reasoning = :reasoning, "
                "qc_completed_at = :completed"
            ),
            ExpressionAttributeValues={
                ":status": verdict["qc_status"],
                ":flags": verdict.get("qc_flags", verdict.get("reasoning", [])),
                ":score": Decimal(str(verdict.get("fashion_score", 5))),
                ":confidence": Decimal(str(verdict.get("confidence_score", 50))),
                ":reasoning": verdict.get("reasoning", verdict.get("qc_flags", [])),
                ":completed": datetime.now(timezone.utc).isoformat(),
            },
        )
        logger.info("[DynamoDB] Successfully updated sku_id=%s → qc_status=%s", sku_id, verdict["qc_status"])
    except ClientError as e:
        logger.error("[DynamoDB] ClientError updating sku_id=%s: %s", sku_id, e.response["Error"]["Message"], exc_info=True)
        raise
    except Exception as e:
        logger.error("[DynamoDB] Unexpected error updating sku_id=%s: %s", sku_id, e, exc_info=True)
        raise


# ═══════════════════════════════════════════════════════════════════
#  Orchestrator — ties everything together
# ═══════════════════════════════════════════════════════════════════

async def orchestrate(sku_id: str, s3_image_url: str, product: dict) -> dict:
    """Run the full multi-agent QC pipeline."""
    logger.info("="*60)
    logger.info("[Orchestrator] START pipeline for sku_id=%s, product=%s", sku_id, product.get("product_name"))
    logger.info("[Orchestrator] S3 image: %s", s3_image_url)

    # Launch all three sub-agents concurrently
    logger.info("[Orchestrator] Launching 3 sub-agents concurrently...")
    visual_task = asyncio.create_task(run_visual_agent(s3_image_url, product))
    commercial_task = asyncio.create_task(run_commercial_agent(product))
    semantic_task = asyncio.create_task(run_semantic_agent(s3_image_url, product))

    results = await asyncio.gather(
        visual_task, commercial_task, semantic_task,
        return_exceptions=True,
    )
    logger.info("[Orchestrator] All 3 sub-agents returned.")

    agent_reports = {}
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            logger.error("[Orchestrator] Sub-agent %d failed: %s", i, r, exc_info=r)
            agent_reports[f"error_{type(r).__name__}"] = {
                "agent": "error",
                "report": json.dumps({"error": str(r), "recommendation": "REVIEW"}),
            }
        else:
            logger.info("[Orchestrator] Sub-agent '%s' completed, report length=%d", r["agent"], len(r["report"]))
            agent_reports[r["agent"]] = r

    visual_report = agent_reports.get("visual", {}).get("report", '{"error": "Visual agent did not run"}')
    commercial_report = agent_reports.get("commercial", {}).get("report", '{"error": "Commercial agent did not run"}')
    semantic_report = agent_reports.get("semantic", {}).get("report", '{"error": "Semantic agent did not run"}')

    logger.info("[Orchestrator] Invoking Judge Agent...")

    # Judge evaluates the combined reports
    verdict = await run_judge_agent(visual_report, commercial_report, semantic_report, product)

    logger.info("[Orchestrator] Judge verdict: %s", json.dumps(verdict))

    # Persist to DynamoDB
    logger.info("[Orchestrator] Persisting verdict to DynamoDB...")
    update_qc_result(sku_id, verdict)

    logger.info("[Orchestrator] END pipeline for sku_id=%s — status=%s", sku_id, verdict["qc_status"])
    logger.info("="*60)

    return {
        "sku_id": sku_id,
        "verdict": verdict,
        "sub_agent_reports": {
            "visual": visual_report,
            "commercial": commercial_report,
            "semantic": semantic_report,
        },
    }


# ═══════════════════════════════════════════════════════════════════
#  Lambda handler
# ═══════════════════════════════════════════════════════════════════

def handler(event, context):
    """
    Lambda entry point.

    Invoked asynchronously by upload_and_trigger Lambda.
    Event: {"sku_id": "...", "s3_image_url": "s3://...", "product": {...}}
    """
    sku_id = event.get("sku_id")
    s3_image_url = event.get("s3_image_url")
    product = event.get("product", {})

    if not sku_id or not s3_image_url:
        logger.error("Missing sku_id or s3_image_url in event: %s", json.dumps(event)[:500])
        return {"statusCode": 400, "body": "Missing required fields"}

    try:
        result = asyncio.run(orchestrate(sku_id, s3_image_url, product))
        return {
            "statusCode": 200,
            "body": json.dumps(result, default=str),
        }
    except Exception as e:
        logger.error("Pipeline failed for sku_id=%s: %s", sku_id, e, exc_info=True)
        try:
            update_qc_result(sku_id, {
                "qc_status": "FLAGGED_FOR_REVIEW",
                "qc_flags": [f"Pipeline error: {str(e)[:200]}"],
                "reasoning": [f"Pipeline error: {str(e)[:200]}"],
                "confidence_score": 0,
                "fashion_score": 0,
            })
        except Exception:
            logger.error("Failed to write error status to DynamoDB", exc_info=True)
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}
