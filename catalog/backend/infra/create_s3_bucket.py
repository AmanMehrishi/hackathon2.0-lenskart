"""
S3 Bucket Creation Script for catalog product images.

Usage:
    python create_s3_bucket.py --bucket my-catalog-qc-images [--region us-east-1]
"""

import argparse

import boto3
from botocore.exceptions import ClientError


DEFAULT_BUCKET = "catalog-qc-product-images"


def create_image_bucket(bucket_name: str, region: str = "us-east-1"):
    """Create the S3 bucket for product images with CORS configured."""

    s3 = boto3.client("s3", region_name=region)

    try:
        create_kwargs = {"Bucket": bucket_name}
        if region != "us-east-1":
            create_kwargs["CreateBucketConfiguration"] = {
                "LocationConstraint": region,
            }
        s3.create_bucket(**create_kwargs)
        print(f"Bucket '{bucket_name}' created.")
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
            print(f"Bucket '{bucket_name}' already exists.")
        else:
            raise

    s3.put_bucket_cors(
        Bucket=bucket_name,
        CORSConfiguration={
            "CORSRules": [
                {
                    "AllowedHeaders": ["*"],
                    "AllowedMethods": ["GET", "PUT", "POST"],
                    "AllowedOrigins": ["*"],
                    "ExposeHeaders": ["ETag"],
                    "MaxAgeSeconds": 3600,
                },
            ],
        },
    )
    print(f"CORS configured on '{bucket_name}'.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create S3 bucket for catalog images")
    parser.add_argument("--bucket", default=DEFAULT_BUCKET, help="S3 bucket name")
    parser.add_argument("--region", default="us-east-1", help="AWS region")
    args = parser.parse_args()

    create_image_bucket(args.bucket, args.region)
