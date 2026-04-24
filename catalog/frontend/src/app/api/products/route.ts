import { NextRequest, NextResponse } from "next/server";
import { QueryCommand, UpdateCommand, ScanCommand } from "@aws-sdk/lib-dynamodb";
import { S3Client, GetObjectCommand } from "@aws-sdk/client-s3";
import { getSignedUrl } from "@aws-sdk/s3-request-presigner";
import { docClient, TABLE_NAME, GSI_NAME } from "@/lib/dynamodb";

const s3 = new S3Client({ region: process.env.AWS_REGION ?? "us-east-1" });

function parseS3Uri(uri: string): { bucket: string; key: string } | null {
  const match = uri.match(/^s3:\/\/([^/]+)\/(.+)$/);
  if (!match) return null;
  return { bucket: match[1], key: match[2] };
}

async function presignProducts(items: Record<string, unknown>[]) {
  return Promise.all(
    items.map(async (item) => {
      const s3Url = item.s3_image_url as string | undefined;
      if (!s3Url) return item;

      const parsed = parseS3Uri(s3Url);
      if (!parsed) return item;

      try {
        const url = await getSignedUrl(
          s3,
          new GetObjectCommand({ Bucket: parsed.bucket, Key: parsed.key }),
          { expiresIn: 3600 }
        );
        return { ...item, s3_image_url: url };
      } catch {
        return item;
      }
    })
  );
}

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const status = searchParams.get("status");

  try {
    let items: Record<string, unknown>[];
    let count: number;

    if (status) {
      const result = await docClient.send(
        new QueryCommand({
          TableName: TABLE_NAME,
          IndexName: GSI_NAME,
          KeyConditionExpression: "qc_status = :status",
          ExpressionAttributeValues: { ":status": status },
          ScanIndexForward: false,
        })
      );
      items = (result.Items ?? []) as Record<string, unknown>[];
      count = result.Count ?? 0;
    } else {
      const result = await docClient.send(
        new ScanCommand({ TableName: TABLE_NAME, Limit: 100 })
      );
      items = (result.Items ?? []) as Record<string, unknown>[];
      count = result.Count ?? 0;
    }

    const products = await presignProducts(items);
    return NextResponse.json({ products, count });
  } catch (error) {
    console.error("GET /api/products error:", error);
    return NextResponse.json(
      { error: "Failed to fetch products" },
      { status: 500 }
    );
  }
}

export async function PATCH(request: NextRequest) {
  try {
    const body = await request.json();
    const { sku_id, new_status } = body;

    if (!sku_id || !new_status) {
      return NextResponse.json(
        { error: "Missing sku_id or new_status" },
        { status: 400 }
      );
    }

    const validStatuses = ["APPROVED", "REJECTED", "FLAGGED_FOR_REVIEW"];
    if (!validStatuses.includes(new_status)) {
      return NextResponse.json(
        { error: `Invalid status. Must be one of: ${validStatuses.join(", ")}` },
        { status: 400 }
      );
    }

    await docClient.send(
      new UpdateCommand({
        TableName: TABLE_NAME,
        Key: { sku_id },
        UpdateExpression:
          "SET qc_status = :status, reviewed_at = :reviewed, reviewed_by = :reviewer",
        ExpressionAttributeValues: {
          ":status": new_status,
          ":reviewed": new Date().toISOString(),
          ":reviewer": "human_reviewer",
        },
      })
    );

    return NextResponse.json({ sku_id, qc_status: new_status, message: "Updated successfully" });
  } catch (error) {
    console.error("PATCH /api/products error:", error);
    return NextResponse.json(
      { error: "Failed to update product" },
      { status: 500 }
    );
  }
}
