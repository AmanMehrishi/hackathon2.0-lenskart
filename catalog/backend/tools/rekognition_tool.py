"""
Real Rekognition tool — analyze_image_technical_specs.

Executes actual Boto3 Rekognition calls:
  - detect_labels:            object/scene classification, bounding boxes
  - detect_moderation_labels: NSFW / unsafe content check
  - detect_faces:             face presence (useful for fashion model shots)

Accepts an S3 URI (s3://bucket/key) and returns structured analysis.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

rekognition = boto3.client("rekognition")


def _parse_s3_uri(s3_uri: str) -> tuple[str, str]:
    """Parse 's3://bucket/key' into (bucket, key)."""
    path = s3_uri.replace("s3://", "")
    bucket, _, key = path.partition("/")
    return bucket, key


def analyze_image_technical_specs(
    s3_image_url: str,
    product_name: str = "",
    category: str = "",
) -> dict[str, Any]:
    """
    Run real Rekognition analysis on an S3 image.

    Returns a dict with:
      - detected_labels: top labels with confidence + bounding boxes
      - moderation_flags: any unsafe content labels
      - faces_detected: count of faces found
      - image_quality: sharpness/brightness estimates from face detection
      - is_safe: bool indicating no moderation flags above threshold
    """
    bucket, key = _parse_s3_uri(s3_image_url)
    s3_image = {"S3Object": {"Bucket": bucket, "Name": key}}

    result: dict[str, Any] = {
        "s3_image_url": s3_image_url,
        "detected_labels": [],
        "moderation_flags": [],
        "faces_detected": 0,
        "image_quality": {},
        "is_safe": True,
        "errors": [],
    }

    # --- detect_labels ---
    try:
        label_resp = rekognition.detect_labels(
            Image=s3_image,
            MaxLabels=20,
            MinConfidence=60.0,
        )
        for label in label_resp.get("Labels", []):
            entry = {
                "name": label["Name"],
                "confidence": round(label["Confidence"], 2),
                "parents": [p["Name"] for p in label.get("Parents", [])],
                "bounding_boxes": [],
            }
            for inst in label.get("Instances", []):
                bb = inst.get("BoundingBox", {})
                if bb:
                    entry["bounding_boxes"].append({
                        "width": round(bb.get("Width", 0), 4),
                        "height": round(bb.get("Height", 0), 4),
                        "left": round(bb.get("Left", 0), 4),
                        "top": round(bb.get("Top", 0), 4),
                    })
            result["detected_labels"].append(entry)
        logger.info("detect_labels returned %d labels", len(result["detected_labels"]))
    except ClientError as e:
        err = f"detect_labels failed: {e.response['Error']['Message']}"
        logger.error(err)
        result["errors"].append(err)

    # --- detect_moderation_labels ---
    try:
        mod_resp = rekognition.detect_moderation_labels(
            Image=s3_image,
            MinConfidence=50.0,
        )
        for mod in mod_resp.get("ModerationLabels", []):
            result["moderation_flags"].append({
                "name": mod["Name"],
                "confidence": round(mod["Confidence"], 2),
                "parent": mod.get("ParentName", ""),
            })
        if result["moderation_flags"]:
            result["is_safe"] = False
        logger.info("detect_moderation_labels returned %d flags", len(result["moderation_flags"]))
    except ClientError as e:
        err = f"detect_moderation_labels failed: {e.response['Error']['Message']}"
        logger.error(err)
        result["errors"].append(err)

    # --- detect_faces (for quality metrics + face count) ---
    try:
        face_resp = rekognition.detect_faces(
            Image=s3_image,
            Attributes=["DEFAULT"],
        )
        faces = face_resp.get("FaceDetails", [])
        result["faces_detected"] = len(faces)
        if faces:
            first = faces[0].get("Quality", {})
            result["image_quality"] = {
                "sharpness": round(first.get("Sharpness", 0), 2),
                "brightness": round(first.get("Brightness", 0), 2),
            }
        logger.info("detect_faces found %d faces", result["faces_detected"])
    except ClientError as e:
        err = f"detect_faces failed: {e.response['Error']['Message']}"
        logger.error(err)
        result["errors"].append(err)

    return result
