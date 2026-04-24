"""
Upload & Trigger Lambda — handles base64 QC image upload to S3, writes a
PENDING record to CatalogQCTable, and triggers the qc_pipeline Lambda.

New flow: vendor submits only product_id + image. Metadata comes from the
CatalogMasterTable golden record (fetched by the pipeline).

Environment variables:
    S3_BUCKET          – target bucket name
    DYNAMODB_TABLE     – CatalogQCTable
    QC_PIPELINE_ARN    – ARN of the qc_pipeline Lambda
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

S3_BUCKET = os.environ.get("S3_BUCKET", "catalog-qc-amogh-km")
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


def _upload_image_to_s3(image_bytes: bytes, upload_id: str, content_type: str) -> str:
    ext_map = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
    ext = ext_map.get(content_type, "jpg")
    key = f"qc-uploads/{upload_id}.{ext}"
    s3.put_object(Bucket=S3_BUCKET, Key=key, Body=image_bytes, ContentType=content_type)
    return f"s3://{S3_BUCKET}/{key}"


def handler(event, context):
    if event.get("httpMethod") == "OPTIONS" or event.get("requestContext", {}).get("http", {}).get("method") == "OPTIONS":
        return _respond(200, {"message": "ok"})

    try:
        raw_body = event.get("body", "{}")
        if event.get("isBase64Encoded"):
            raw_body = base64.b64decode(raw_body).decode()
        body = json.loads(raw_body)
    except (json.JSONDecodeError, TypeError):
        return _respond(400, {"error": "Invalid JSON body"})

    image_b64 = body.get("image_base64")
    if not image_b64:
        return _respond(400, {"error": "Missing 'image_base64' field"})

    product_id = body.get("product_id", "").strip()
    proposed_price = body.get("proposed_price", 0)
    product = body.get("product", {})
    product_name = product.get("product_name", "") if product else ""

    if not product_id and not product_name:
        return _respond(400, {"error": "Missing 'product_id' or 'product.product_name'"})

    content_type = body.get("content_type", "image/jpeg")

    try:
        image_bytes = base64.b64decode(image_b64)
    except Exception:
        return _respond(400, {"error": "Invalid base64 image data"})

    upload_id = f"QC-{uuid.uuid4().hex[:12].upper()}"

    try:
        s3_url = _upload_image_to_s3(image_bytes, upload_id, content_type)
    except ClientError as e:
        return _respond(500, {"error": f"S3 upload failed: {e}"})

    try:
        table.put_item(
            Item={
                "sku_id": upload_id,
                "product_id": product_id,
                "product_name": product_name or product_id,
                "proposed_price": str(proposed_price or product.get("proposed_price", 0)),
                "category": product.get("category", "") if product else "",
                "brand": product.get("brand", "") if product else "",
                "s3_image_url": s3_url,
                "qc_status": "PENDING",
                "qc_flags": [],
                "reasoning": [],
                "confidence_score": 0,
                "fashion_score": 0,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    except ClientError as e:
        return _respond(500, {"error": f"DynamoDB write failed: {e}"})

    pipeline_payload = {
        "sku_id": upload_id,
        "s3_image_url": s3_url,
        "product_id": product_id,
        "proposed_price": proposed_price,
        "product": product,
    }

    pipeline_invoked = False
    if QC_PIPELINE_ARN:
        try:
            lambda_client.invoke(
                FunctionName=QC_PIPELINE_ARN,
                InvocationType="Event",
                Payload=json.dumps(pipeline_payload).encode(),
            )
            pipeline_invoked = True
        except Exception as e:
            return _respond(500, {"error": f"Pipeline invoke failed: {e}"})

    return _respond(200, {
        "sku_id": upload_id,
        "product_id": product_id,
        "s3_image_url": s3_url,
        "qc_status": "PENDING",
        "pipeline_invoked": pipeline_invoked,
    })
