"""
QC Pipeline Lambda — Multi-Model Microservice Orchestrator.

Architecture:
  1. Semantic Agent    (amazon.nova-micro-v1:0)  — text-only metadata & price check
  2. Condition Agent   (Amazon Rekognition)       — defect detection via detect_labels
  3. Visual Matcher    (Claude Sonnet)            — dual-image structural comparison
  4. Judge Agent       (Claude Sonnet)            — final verdict synthesis

Environment variables:
    DYNAMODB_TABLE      – CatalogQCTable
    MASTER_TABLE        – CatalogMasterTable
    S3_BUCKET           – image bucket
    BEDROCK_TEXT_MODEL   – fast text-only model for Semantic Agent
    BEDROCK_SMART_MODEL  – Sonnet for Visual Matcher + Judge
    AWS_REGION_NAME     – defaults to us-east-1
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from tools.rekognition_tool import analyze_image_technical_specs

logger = logging.getLogger()
logger.setLevel(logging.INFO)

DYNAMODB_TABLE = os.environ.get("DYNAMODB_TABLE", "CatalogQCTable")
MASTER_TABLE = os.environ.get("MASTER_TABLE", "CatalogMasterTable")
BEDROCK_TEXT_MODEL = os.environ.get("BEDROCK_TEXT_MODEL", "amazon.nova-micro-v1:0")
BEDROCK_SMART_MODEL = os.environ.get("BEDROCK_SMART_MODEL", "us.anthropic.claude-sonnet-4-6")
REGION = os.environ.get("AWS_REGION_NAME", "us-east-1")

bedrock = boto3.client("bedrock-runtime", region_name=REGION)
rekognition = boto3.client("rekognition", region_name=REGION)
dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(DYNAMODB_TABLE)
master_table = dynamodb.Table(MASTER_TABLE)
s3_client_global = boto3.client("s3", region_name=REGION)


# ═══════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════

def fetch_golden_record(product_id: str) -> dict | None:
    if not product_id:
        return None
    try:
        resp = master_table.get_item(Key={"product_id": product_id})
        item = resp.get("Item")
        if item:
            logger.info("[GoldenRecord] Found record for product_id=%s", product_id)
        else:
            logger.warning("[GoldenRecord] Not found: product_id=%s", product_id)
        return item
    except ClientError as e:
        logger.error("[GoldenRecord] Error: %s", e.response["Error"]["Message"])
        return None


def _load_s3_image(s3_uri: str) -> tuple[bytes, str]:
    bucket, key = s3_uri.replace("s3://", "").split("/", 1)
    obj = s3_client_global.get_object(Bucket=bucket, Key=key)
    image_bytes = obj["Body"].read()
    ct = obj.get("ContentType", "image/jpeg")
    fmt_map = {"image/jpeg": "jpeg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}
    return image_bytes, fmt_map.get(ct, "jpeg")


def _converse(
    system_prompt: str,
    messages: list[dict],
    tool_config: dict | None = None,
    max_tokens: int = 4096,
    model_id: str | None = None,
) -> dict:
    resolved_model = model_id or BEDROCK_TEXT_MODEL
    kwargs: dict[str, Any] = {
        "modelId": resolved_model,
        "system": [{"text": system_prompt}],
        "messages": messages,
        "inferenceConfig": {"maxTokens": max_tokens, "temperature": 0.2},
    }
    if tool_config:
        kwargs["toolConfig"] = tool_config
    logger.info("Calling Bedrock Converse (model=%s, messages=%d)", resolved_model, len(messages))
    return bedrock.converse(**kwargs)


def _extract_text(response: dict) -> str:
    parts = []
    for block in response.get("output", {}).get("message", {}).get("content", []):
        if "text" in block:
            parts.append(block["text"])
    return "\n".join(parts)


# ═══════════════════════════════════════════════════════════════════
#  Agent 1: Semantic Agent — text-only metadata & price check
#  Model: amazon.nova-micro-v1:0 (fast, cheap, text-only)
# ═══════════════════════════════════════════════════════════════════

async def run_semantic_agent(product: dict, golden_record: dict | None) -> dict:
    expected_price = float(golden_record.get("expected_price", 0)) if golden_record else 0
    proposed_price = float(product.get("proposed_price", 0))

    if expected_price > 0 and proposed_price > 0:
        deviation_pct = abs(proposed_price - expected_price) / expected_price * 100
    else:
        deviation_pct = 0

    system_prompt = (
        "You are a text-only metadata and pricing validator for an eyewear catalog.\n\n"
        "You are evaluating a vendor's proposed_price against a Master Database expected_price. "
        "DO NOT compare to real-world market averages or external pricing logic. "
        "If proposed_price matches expected_price within a 45% margin, consider it valid.\n\n"
        "The Master Database metadata is the ABSOLUTE Source of Truth. "
        "DO NOT debate terminology. If the DB says 'Cat Eye', it IS Cat Eye.\n\n"
        "Check:\n"
        "1. Required fields present: product name/id, brand, category, price.\n"
        "2. Price deviation within 45% of expected_price → PASS. Over 45% → REVIEW.\n\n"
        "Output ONLY a JSON object:\n"
        '{"required_fields_present": true/false, "missing_fields": [], '
        '"proposed_price": number, "expected_price": number, "price_deviation_pct": number, '
        '"price_assessment": "VALID" or "FLAGGED", '
        '"recommendation": "PASS" or "REVIEW"}'
    )

    user_msg = (
        f"Product ID: {product.get('product_id', product.get('product_name', 'N/A'))}\n"
        f"Brand: {product.get('brand', 'N/A')}\n"
        f"Category: {product.get('category', 'N/A')}\n"
        f"Proposed Price: ${proposed_price}\n"
        f"Expected Price (Master DB): ${expected_price}\n"
        f"Price Deviation: {deviation_pct:.1f}%\n"
        f"Frame Shape: {golden_record.get('frame_shape', 'N/A') if golden_record else 'N/A'}\n"
        f"Frame Type: {golden_record.get('frame_type', 'N/A') if golden_record else 'N/A'}\n"
        f"Frame Color: {golden_record.get('frame_color', 'N/A') if golden_record else 'N/A'}\n\n"
        f"Validate and return your JSON report."
    )

    messages = [{"role": "user", "content": [{"text": user_msg}]}]
    logger.info("[Semantic Agent] START — text-only check (model=%s)", BEDROCK_TEXT_MODEL)

    response = await asyncio.to_thread(_converse, system_prompt, messages, None, 1024, BEDROCK_TEXT_MODEL)
    final_text = _extract_text(response)
    logger.info("[Semantic Agent] DONE — length=%d", len(final_text))
    return {"agent": "semantic", "report": final_text}


# ═══════════════════════════════════════════════════════════════════
#  Agent 2: Condition Agent — Rekognition defect detection (NO LLM)
# ═══════════════════════════════════════════════════════════════════

DEFECT_LABELS = {
    "scratch", "crack", "broken", "damage", "damaged", "blemish",
    "dent", "chip", "fracture", "flaw", "defect", "bent", "warped",
    "stain", "discoloration", "smudge", "fingerprint",
}
SEVERE_DEFECTS = {"crack", "broken", "fracture", "damage", "damaged"}
MINOR_DEFECTS = {"scratch", "blemish", "smudge", "fingerprint", "stain", "dent", "chip", "discoloration"}


async def run_condition_agent(s3_image_url: str) -> dict:
    """Pure Rekognition — no LLM needed. Parses labels for defect indicators."""
    logger.info("[Condition Agent] START — Rekognition defect scan on %s", s3_image_url)

    bucket, key = s3_image_url.replace("s3://", "").split("/", 1)
    s3_image = {"S3Object": {"Bucket": bucket, "Name": key}}

    try:
        label_resp = await asyncio.to_thread(
            rekognition.detect_labels,
            Image=s3_image, MaxLabels=30, MinConfidence=50.0,
        )
    except ClientError as e:
        err = f"Rekognition detect_labels failed: {e.response['Error']['Message']}"
        logger.error("[Condition Agent] %s", err)
        return {"agent": "condition", "report": json.dumps({"condition": "UNKNOWN", "error": err})}

    all_labels = [l["Name"].lower() for l in label_resp.get("Labels", [])]
    severe_found = [l for l in all_labels if l in SEVERE_DEFECTS]
    minor_found = [l for l in all_labels if l in MINOR_DEFECTS]

    if severe_found:
        condition = "REJECT"
        detail = f"Severe defects detected: {', '.join(severe_found)}"
    elif minor_found:
        condition = "FLAG"
        detail = f"Minor anomalies detected: {', '.join(minor_found)}"
    else:
        condition = "INTACT"
        detail = "No defects or damage indicators found"

    report = {
        "condition": condition,
        "detail": detail,
        "severe_defects": severe_found,
        "minor_defects": minor_found,
        "all_labels": all_labels[:15],
    }

    logger.info("[Condition Agent] DONE — condition=%s, severe=%s, minor=%s",
                condition, severe_found, minor_found)
    return {"agent": "condition", "report": json.dumps(report)}


# ═══════════════════════════════════════════════════════════════════
#  Agent 3: Visual Matcher — dual-image structural comparison
#  Model: Claude Sonnet (multi-image capable)
# ═══════════════════════════════════════════════════════════════════

async def run_visual_matcher_agent(
    qc_image_url: str,
    golden_image_url: str | None,
    golden_record: dict | None,
    product: dict,
) -> dict:
    system_prompt = (
        "You are a visual product matcher and physical inspector for an EYEWEAR catalog.\n\n"
        "CRITICAL: If the QC image does NOT show eyewear → FAIL: \"Item is not eyewear.\"\n\n"
        "You receive two images:\n"
        "- Image 1: Golden Reference (master-approved product)\n"
        "- Image 2: QC Upload (vendor's submission)\n\n"
        "Your job has TWO parts:\n\n"
        "PART 1 — STRUCTURAL MATCH:\n"
        "Compare Image 2 against Image 1. Verify frame shape, color, and structural "
        "characteristics match. Report structural_match as true/false.\n"
        "If the QC image is a completely different product (wrong shape, wrong color, wrong "
        "material), report structural_match=false and sku_mismatch=true.\n\n"
        "PART 2 — DAMAGE ASSESSMENT:\n"
        "Closely inspect the QC image for physical damage: bent frames, detached or loose "
        "temple arms, missing lenses, deep scratches, cracks, chips, severe discoloration, "
        "or heavy wear. Report damage_found as true/false with a damage_details string.\n\n"
        "Output JSON:\n"
        '{"is_eyewear": true/false, "structural_match": true/false, '
        '"sku_mismatch": true/false, '
        '"match_details": "description", '
        '"damage_found": true/false, '
        '"damage_details": "none" or "description of damage", '
        '"image_quality_score": 1-10, '
        '"is_safe": true/false, "issues": [], "recommendation": "PASS"/"FAIL"/"REVIEW"}'
    )

    user_content: list[dict] = []

    if golden_image_url:
        try:
            golden_bytes, golden_fmt = await asyncio.to_thread(_load_s3_image, golden_image_url)
            user_content.append({"text": "IMAGE 1 — Golden Reference:"})
            user_content.append({"image": {"format": golden_fmt, "source": {"bytes": golden_bytes}}})
        except Exception as e:
            logger.warning("[Visual Matcher] Golden image unavailable: %s", e)
            user_content.append({"text": f"(Golden image unavailable: {e})"})

    try:
        qc_bytes, qc_fmt = await asyncio.to_thread(_load_s3_image, qc_image_url)
        user_content.append({"text": "IMAGE 2 — QC Upload:"})
        user_content.append({"image": {"format": qc_fmt, "source": {"bytes": qc_bytes}}})
    except Exception as e:
        logger.error("[Visual Matcher] QC image load failed: %s", e)
        return {"agent": "visual", "report": json.dumps({"error": str(e), "recommendation": "REVIEW"})}

    golden_meta = ""
    if golden_record:
        golden_meta = (
            f"\nGolden Record: Brand={golden_record.get('brand','N/A')}, "
            f"Shape={golden_record.get('frame_shape','N/A')}, "
            f"Color={golden_record.get('frame_color','N/A')}"
        )

    user_content.append({"text": (
        f"Product: {product.get('product_name', product.get('product_id', 'Unknown'))}\n"
        f"Category: {product.get('category', 'Eyewear')}{golden_meta}\n\n"
        f"Compare both images and give your JSON report."
    )})

    messages = [{"role": "user", "content": user_content}]
    logger.info("[Visual Matcher] START — dual-image (golden=%s, model=%s)", bool(golden_image_url), BEDROCK_SMART_MODEL)

    response = await asyncio.to_thread(_converse, system_prompt, messages, None, 2048, BEDROCK_SMART_MODEL)
    final_text = _extract_text(response)
    logger.info("[Visual Matcher] DONE — length=%d", len(final_text))
    return {"agent": "visual", "report": final_text}


# ═══════════════════════════════════════════════════════════════════
#  Judge Agent — final verdict synthesis
#  Model: Claude Sonnet
# ═══════════════════════════════════════════════════════════════════

async def run_judge_agent(
    visual_report: str,
    condition_report: str,
    semantic_report: str,
    product: dict,
    golden_record: dict | None = None,
) -> dict:
    system_prompt = (
        "You are a senior QA Manager rendering the final quality verdict for an EYEWEAR catalog.\n\n"
        "You receive: Visual Matcher report, Condition report (Rekognition), Semantic report (metadata/price).\n\n"
        "ABSOLUTE REJECTION RULES (non-negotiable, checked FIRST):\n\n"
        "Rule 1 — DUAL-VETO DAMAGE: If EITHER the Condition report OR the Visual Matcher report "
        "indicates physical damage (bent frames, detached temple arms, deep cracks, missing lenses, "
        "severe wear), output REJECTED instantly. Do NOT flag for review.\n\n"
        "Rule 2 — TOTAL SKU MISMATCH: If the Visual Matcher reports the QC image is structurally "
        "a completely different item from the Golden Image (sku_mismatch=true, wrong shape, wrong "
        "color, wrong material), output REJECTED instantly. Do NOT flag for review.\n\n"
        "Rule 3 — NOT EYEWEAR: If the Visual Matcher says the item is not eyewear → REJECTED.\n\n"
        "Rule 4 — SAFETY: NSFW or unsafe content → REJECTED.\n\n"
        "APPROVAL/FLAG RULES (only if no rejection rules triggered):\n\n"
        "5. MASTER DB SUPREMACY: The Master Database is absolute law. If the Visual Matcher "
        "confirms structural match AND no damage, ignore any complaints about shape terminology "
        "or category labels.\n"
        "   - Visual match + no damage + price within 45% → APPROVED.\n"
        "   - Visual match + no damage + price deviation > 45% → already handled by pre-check, "
        "     but if reached, FLAGGED_FOR_REVIEW.\n"
        "   - Minor visual discrepancies (lighting, angle) but same product → FLAGGED_FOR_REVIEW.\n\n"
        "CONFIDENCE SCORING (0-100): Grade your certainty.\n\n"
        "REASONING RULES:\n"
        "- NEVER mention internal terms like 'Visual Agent', 'Condition Agent', 'sub-agents', 'pipeline'.\n"
        "- One short factual sentence per reason.\n"
        "- APPROVED: [\"Product metadata aligns with visual inspection and pricing is within standard bounds.\"]\n"
        "- REJECTED non-eyewear: [\"Image does not depict valid eyewear.\"]\n"
        "- REJECTED damage: [\"Physical defect detected: <specific damage>.\"]\n"
        "- REJECTED mismatch: [\"Product does not match registered SKU: <specific difference>.\"]\n"
        "- FLAGGED: State the specific issue concisely.\n\n"
        "Output ONLY raw JSON:\n"
        '{"qc_status":"APPROVED"|"REJECTED"|"FLAGGED_FOR_REVIEW",'
        '"confidence_score":<0-100>,"fashion_score":<1-10>,"reasoning":["..."]}'
    )

    golden_meta = ""
    if golden_record:
        golden_meta = (
            f"\n=== GOLDEN RECORD ===\n"
            f"Product ID: {golden_record.get('product_id','N/A')}\n"
            f"Brand: {golden_record.get('brand','N/A')}\n"
            f"Expected Price: ${golden_record.get('expected_price','N/A')}\n"
            f"Category: {golden_record.get('category','N/A')}\n"
            f"Frame Shape: {golden_record.get('frame_shape','N/A')}\n"
            f"Frame Type: {golden_record.get('frame_type','N/A')}\n"
            f"Frame Color: {golden_record.get('frame_color','N/A')}\n"
        )

    user_msg = (
        f"Product: {product.get('product_name', product.get('product_id','Unknown'))} | "
        f"Proposed Price: ${product.get('proposed_price',0)}\n"
        f"{golden_meta}\n"
        f"=== VISUAL MATCHER REPORT ===\n{visual_report}\n\n"
        f"=== CONDITION REPORT (Rekognition) ===\n{condition_report}\n\n"
        f"=== SEMANTIC REPORT (Metadata/Price) ===\n{semantic_report}\n\n"
        f"Render your final JSON verdict."
    )

    messages = [{"role": "user", "content": [{"text": user_msg}]}]
    logger.info("[Judge] START (model=%s)", BEDROCK_SMART_MODEL)
    response = await asyncio.to_thread(_converse, system_prompt, messages, None, 1024, BEDROCK_SMART_MODEL)

    raw = _extract_text(response)
    logger.info("[Judge] Raw output: %s", raw[:1000])
    return _parse_judge_output(raw)


def _parse_judge_output(raw: str) -> dict:
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
                verdict = {"qc_status": "FLAGGED_FOR_REVIEW", "confidence_score": 0,
                           "reasoning": ["Unparseable AI output"], "fashion_score": 5}
        else:
            verdict = {"qc_status": "FLAGGED_FOR_REVIEW", "confidence_score": 0,
                       "reasoning": ["No JSON in AI output"], "fashion_score": 5}

    valid = {"APPROVED", "REJECTED", "FLAGGED_FOR_REVIEW"}
    if verdict.get("qc_status") not in valid:
        verdict["qc_status"] = "FLAGGED_FOR_REVIEW"
    if not isinstance(verdict.get("confidence_score"), (int, float)):
        verdict["confidence_score"] = 50
    verdict["confidence_score"] = max(0, min(100, int(verdict["confidence_score"])))
    if not isinstance(verdict.get("fashion_score"), (int, float)):
        verdict["fashion_score"] = 5
    if not isinstance(verdict.get("reasoning"), list):
        verdict["reasoning"] = verdict.get("qc_flags", []) if isinstance(verdict.get("qc_flags"), list) else []
    verdict["qc_flags"] = verdict["reasoning"]
    return verdict


# ═══════════════════════════════════════════════════════════════════
#  DynamoDB update
# ═══════════════════════════════════════════════════════════════════

def update_qc_result(sku_id: str, verdict: dict) -> None:
    logger.info("[DynamoDB] Updating sku_id=%s → status=%s, confidence=%s",
                sku_id, verdict["qc_status"], verdict.get("confidence_score"))
    try:
        table.update_item(
            Key={"sku_id": sku_id},
            UpdateExpression=(
                "SET qc_status = :status, qc_flags = :flags, fashion_score = :score, "
                "confidence_score = :confidence, reasoning = :reasoning, qc_completed_at = :completed"
            ),
            ExpressionAttributeValues={
                ":status": verdict["qc_status"],
                ":flags": verdict.get("qc_flags", []),
                ":score": Decimal(str(verdict.get("fashion_score", 5))),
                ":confidence": Decimal(str(verdict.get("confidence_score", 50))),
                ":reasoning": verdict.get("reasoning", []),
                ":completed": datetime.now(timezone.utc).isoformat(),
            },
        )
        logger.info("[DynamoDB] Success: sku_id=%s", sku_id)
    except ClientError as e:
        logger.error("[DynamoDB] Error: %s", e.response["Error"]["Message"], exc_info=True)
        raise


# ═══════════════════════════════════════════════════════════════════
#  Orchestrator — parallel microservice execution
# ═══════════════════════════════════════════════════════════════════

async def orchestrate(sku_id: str, s3_image_url: str, product: dict, product_id: str = "") -> dict:
    logger.info("=" * 60)
    logger.info("[Orchestrator] START sku_id=%s product_id=%s", sku_id, product_id)

    golden_record = await asyncio.to_thread(fetch_golden_record, product_id)
    golden_image_url = golden_record.get("golden_image_url", "") if golden_record else ""

    if golden_record:
        if not product.get("product_name"):
            product["product_name"] = golden_record.get("brand", product_id)
        if not product.get("brand"):
            product["brand"] = golden_record.get("brand", "")
        if not product.get("category"):
            product["category"] = golden_record.get("category", golden_record.get("frame_shape", "Eyewear"))
        if not product.get("proposed_price"):
            product["proposed_price"] = golden_record.get("expected_price", 0)

    # ── Deterministic pre-AI price gate ──
    proposed = float(product.get("proposed_price", 0))
    expected = float(golden_record.get("expected_price", 0)) if golden_record else 0
    if proposed > 0 and expected > 0:
        price_variance_pct = abs(proposed - expected) / expected * 100
        if price_variance_pct > 45:
            reason = (
                f"Price violation: proposed ${proposed:.2f} deviates "
                f"{price_variance_pct:.1f}% from expected ${expected:.2f} (threshold: 45%)."
            )
            logger.warning("[Orchestrator] PRE-AI REJECT — %s", reason)
            verdict = {
                "qc_status": "REJECTED",
                "confidence_score": 99,
                "fashion_score": 0,
                "reasoning": [reason],
                "qc_flags": [reason],
            }
            update_qc_result(sku_id, verdict)
            logger.info("[Orchestrator] END sku_id=%s — deterministic price rejection", sku_id)
            return {"sku_id": sku_id, "product_id": product_id, "verdict": verdict, "sub_agent_reports": {}}

    logger.info("[Orchestrator] Launching 3 agents in parallel...")
    semantic_task = asyncio.create_task(run_semantic_agent(product, golden_record))
    condition_task = asyncio.create_task(run_condition_agent(s3_image_url))
    visual_task = asyncio.create_task(
        run_visual_matcher_agent(s3_image_url, golden_image_url or None, golden_record, product)
    )

    results = await asyncio.gather(semantic_task, condition_task, visual_task, return_exceptions=True)
    logger.info("[Orchestrator] All 3 agents returned.")

    reports = {}
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            logger.error("[Orchestrator] Agent %d failed: %s", i, r)
            reports[f"error_{i}"] = {"agent": "error", "report": json.dumps({"error": str(r)})}
        else:
            reports[r["agent"]] = r

    semantic_report = reports.get("semantic", {}).get("report", '{"error":"semantic agent failed"}')
    condition_report = reports.get("condition", {}).get("report", '{"error":"condition agent failed"}')
    visual_report = reports.get("visual", {}).get("report", '{"error":"visual agent failed"}')

    logger.info("[Orchestrator] Invoking Judge...")
    verdict = await run_judge_agent(visual_report, condition_report, semantic_report, product, golden_record)

    logger.info("[Orchestrator] Verdict: %s", json.dumps(verdict))
    update_qc_result(sku_id, verdict)
    logger.info("[Orchestrator] END sku_id=%s status=%s", sku_id, verdict["qc_status"])
    logger.info("=" * 60)

    return {
        "sku_id": sku_id,
        "product_id": product_id,
        "verdict": verdict,
        "sub_agent_reports": {
            "visual": visual_report,
            "condition": condition_report,
            "semantic": semantic_report,
        },
    }


# ═══════════════════════════════════════════════════════════════════
#  Lambda handler
# ═══════════════════════════════════════════════════════════════════

def handler(event, context):
    sku_id = event.get("sku_id")
    s3_image_url = event.get("s3_image_url")
    product_id = event.get("product_id", "")
    proposed_price = event.get("proposed_price", 0)
    product = event.get("product", {})
    if proposed_price and not product.get("proposed_price"):
        product["proposed_price"] = proposed_price

    if not sku_id or not s3_image_url:
        logger.error("Missing fields: %s", json.dumps(event)[:500])
        return {"statusCode": 400, "body": "Missing required fields"}

    try:
        result = asyncio.run(orchestrate(sku_id, s3_image_url, product, product_id))
        return {"statusCode": 200, "body": json.dumps(result, default=str)}
    except Exception as e:
        logger.error("Pipeline failed for %s: %s", sku_id, e, exc_info=True)
        try:
            update_qc_result(sku_id, {
                "qc_status": "FLAGGED_FOR_REVIEW",
                "qc_flags": [f"Pipeline error: {str(e)[:200]}"],
                "reasoning": [f"Pipeline error: {str(e)[:200]}"],
                "confidence_score": 0, "fashion_score": 0,
            })
        except Exception:
            logger.error("Failed to write error status", exc_info=True)
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}
