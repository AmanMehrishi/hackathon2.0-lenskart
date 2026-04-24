"""
DynamoDB Table Creation Script for CatalogQCTable.

Usage:
    python create_table.py [--region us-east-1] [--endpoint-url http://localhost:8000]

The --endpoint-url flag is useful for local DynamoDB testing.
"""

import argparse
import sys
import time

import boto3
from botocore.exceptions import ClientError


TABLE_NAME = "CatalogQCTable"
PARTITION_KEY = "sku_id"


def create_catalog_qc_table(
    region: str = "us-east-1",
    endpoint_url: str | None = None,
) -> dict:
    """Create the CatalogQCTable in DynamoDB with on-demand billing."""

    kwargs = {"region_name": region}
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url

    dynamodb = boto3.resource("dynamodb", **kwargs)

    try:
        table = dynamodb.create_table(
            TableName=TABLE_NAME,
            KeySchema=[
                {"AttributeName": PARTITION_KEY, "KeyType": "HASH"},
            ],
            AttributeDefinitions=[
                {"AttributeName": PARTITION_KEY, "AttributeType": "S"},
                {"AttributeName": "qc_status", "AttributeType": "S"},
                {"AttributeName": "created_at", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "qc_status-created_at-index",
                    "KeySchema": [
                        {"AttributeName": "qc_status", "KeyType": "HASH"},
                        {"AttributeName": "created_at", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        print(f"Creating table '{TABLE_NAME}'...")
        table.wait_until_exists()
        print(f"Table '{TABLE_NAME}' is ACTIVE.")
        return table.table_status

    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceInUseException":
            print(f"Table '{TABLE_NAME}' already exists.")
            table = dynamodb.Table(TABLE_NAME)
            return table.table_status
        raise


def verify_table(region: str = "us-east-1", endpoint_url: str | None = None):
    """Print table description to verify creation."""

    kwargs = {"region_name": region}
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url

    client = boto3.client("dynamodb", **kwargs)
    resp = client.describe_table(TableName=TABLE_NAME)
    info = resp["Table"]

    print(f"\n--- Table Info ---")
    print(f"  Name:       {info['TableName']}")
    print(f"  Status:     {info['TableStatus']}")
    print(f"  Item Count: {info['ItemCount']}")
    print(f"  Key Schema: {info['KeySchema']}")

    for gsi in info.get("GlobalSecondaryIndexes", []):
        print(f"  GSI:        {gsi['IndexName']}  Keys: {gsi['KeySchema']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create CatalogQCTable in DynamoDB")
    parser.add_argument("--region", default="us-east-1", help="AWS region")
    parser.add_argument("--endpoint-url", default=None, help="DynamoDB endpoint (for local dev)")
    args = parser.parse_args()

    create_catalog_qc_table(region=args.region, endpoint_url=args.endpoint_url)
    verify_table(region=args.region, endpoint_url=args.endpoint_url)
