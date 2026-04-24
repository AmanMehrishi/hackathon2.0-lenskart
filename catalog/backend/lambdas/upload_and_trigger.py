"""
Upload & Trigger Lambda — handles base64 image upload to S3 and returns
the S3 URI so the frontend (or API Gateway) can chain into the QC pipeline.

Environment variables (set in Lambda console / SAM template):
    S3_BUCKET          – target bucket name
    DYNAMODB_TABLE     – CatalogQCTable
    QC_PIPELINE_ARN    – ARN of the qc_pipeline Lambda (optional async invoke)
    AWS_REGION_NAME    – defaults to us-east-1
"""

from __future__ import annotations

import base64
import json
import os
import uuid
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

S3_BUCKET = os.environ.get("S3_BUCKET", "catalog-qc-product-images")
DYNAMODB_TABLE = os.environ.get("DYNAMODB_TABLE", "CatalogQCTable")
QC_PIPELINE_ARN = os.environ.get("QC_PIPELINE_ARN", "")
REGION = os.environ.get("AWS_REGION_NAME", "us-east-1")

s3 = boto3.client("s3", region_name=REGION)
dynamodb = boto3.resource("dynamodb", region_name=REGION)
lambda_client = boto3.client("lambda", region_name=REGION)
table = dynamodb.Table(DYNAMODB_TABLE)


def _respond(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
        },
        "body": json.dumps(body),
    }


def _upload_image_to_s3(image_bytes: bytes, sku_id: str, content_type: str) -> str:
    """Upload raw image bytes to S3 and return the s3:// URI."""
    ext_map = {
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
    }
    ext = ext_map.get(content_type, "jpg")
    key = f"uploads/{sku_id}.{ext}"

    s3.put_object(
        Bucket=S3_BUCKET,
        Key=key,
        Body=image_bytes,
        ContentType=content_type,
    )
    return f"s3://{S3_BUCKET}/{key}"


def _save_initial_record(sku_id: str, product: dict, s3_url: str) -> None:
    """Write the initial SKU record to DynamoDB (qc_status = PENDING)."""
    table.put_item(
        Item={
            "sku_id": sku_id,
            "product_name": product.get("product_name", "Untitled"),
            "proposed_price": str(product.get("proposed_price", 0)),
            "category": product.get("category", ""),
            "brand": product.get("brand", ""),
            "attributes": product.get("attributes", {}),
            "s3_image_url": s3_url,
            "qc_status": "PENDING",
            "qc_flags": [],
            "fashion_score": 0,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )


def _invoke_qc_pipeline(sku_id: str, s3_url: str, product: dict) -> dict | None:
    """
    Invoke the QC pipeline Lambda asynchronously.
    Returns the invocation response or None if no ARN is configured.
    """
    if not QC_PIPELINE_ARN:
        return None

    payload = {
        "sku_id": sku_id,
        "s3_image_url": s3_url,
        "product": product,
    }

    response = lambda_client.invoke(
        FunctionName=QC_PIPELINE_ARN,
        InvocationType="Event",  # async fire-and-forget
        Payload=json.dumps(payload).encode(),
    )
    return {"StatusCode": response["StatusCode"]}


def handler(event, context):
    """
    API Gateway proxy handler.

    Expects JSON body:
    {
        "image_base64": "<base64 encoded image>",
        "content_type": "image/jpeg",        // optional, defaults to image/jpeg
        "product": {
            "product_name": "Blue Denim Jacket",
            "proposed_price": 89.99,
            "category": "Outerwear > Jackets",
            "brand": "UrbanEdge",
            "attributes": {
                "color": "blue",
                "material": "denim",
                "size_available": ["S", "M", "L", "XL"]
            }
        }
    }
    """
    # Handle CORS preflight
    if event.get("httpMethod") == "OPTIONS":
        return _respond(200, {"message": "ok"})

    try:
        body = json.loads(event.get("body", "{}"))
    except (json.JSONDecodeError, TypeError):
        return _respond(400, {"error": "Invalid JSON body"})

    image_b64 = body.get("image_base64")
    if not image_b64:
        return _respond(400, {"error": "Missing 'image_base64' field"})

    product = body.get("product", {})
    if not product.get("product_name"):
        return _respond(400, {"error": "Missing 'product.product_name'"})

    content_type = body.get("content_type", "image/jpeg")

    try:
        image_bytes = base64.b64decode(image_b64)
    except Exception:
        return _respond(400, {"error": "Invalid base64 image data"})

    sku_id = f"SKU-{uuid.uuid4().hex[:12].upper()}"

    try:
        s3_url = _upload_image_to_s3(image_bytes, sku_id, content_type)
    except ClientError as e:
        return _respond(500, {"error": f"S3 upload failed: {e}"})

    try:
        _save_initial_record(sku_id, product, s3_url)
    except ClientError as e:
        return _respond(500, {"error": f"DynamoDB write failed: {e}"})

    pipeline_response = _invoke_qc_pipeline(sku_id, s3_url, product)

    return _respond(200, {
        "sku_id": sku_id,
        "s3_image_url": s3_url,
        "qc_status": "PENDING",
        "pipeline_invoked": pipeline_response is not None,
        "message": "Product uploaded. QC pipeline triggered."
            if pipeline_response
            else "Product uploaded. Trigger QC pipeline manually or set QC_PIPELINE_ARN.",
    })
