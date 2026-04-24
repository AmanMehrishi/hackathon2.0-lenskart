import { NextRequest, NextResponse } from "next/server";
import { PutCommand, ScanCommand } from "@aws-sdk/lib-dynamodb";
import { S3Client, PutObjectCommand } from "@aws-sdk/client-s3";
import { docClient, MASTER_TABLE_NAME, S3_BUCKET } from "@/lib/dynamodb";

const s3 = new S3Client({ region: process.env.AWS_REGION ?? "us-east-1" });

export async function GET() {
  try {
    const result = await docClient.send(
      new ScanCommand({ TableName: MASTER_TABLE_NAME, Limit: 200 })
    );
    return NextResponse.json({ products: result.Items ?? [], count: result.Count ?? 0 });
  } catch (error) {
    console.error("GET /api/master error:", error);
    return NextResponse.json({ error: "Failed to fetch master catalog" }, { status: 500 });
  }
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { product_id, brand, expected_price, category, frame_shape, frame_type, frame_color, image_base64, content_type } = body;

    if (!product_id || !brand || !expected_price || !category) {
      return NextResponse.json({ error: "Missing required fields: product_id, brand, expected_price, category" }, { status: 400 });
    }

    let golden_image_url = "";
    if (image_base64) {
      const imageBytes = Buffer.from(image_base64, "base64");
      const ext = (content_type === "image/png") ? "png" : (content_type === "image/webp") ? "webp" : "jpg";
      const key = `golden/${product_id}.${ext}`;

      await s3.send(new PutObjectCommand({
        Bucket: S3_BUCKET,
        Key: key,
        Body: imageBytes,
        ContentType: content_type || "image/jpeg",
      }));
      golden_image_url = `s3://${S3_BUCKET}/${key}`;
    }

    await docClient.send(
      new PutCommand({
        TableName: MASTER_TABLE_NAME,
        Item: {
          product_id,
          brand,
          expected_price: Number(expected_price),
          category: category || "",
          frame_shape: frame_shape || "",
          frame_type: frame_type || "",
          frame_color: frame_color || "",
          golden_image_url,
          registered_at: new Date().toISOString(),
        },
      })
    );

    return NextResponse.json({ product_id, golden_image_url, message: "Golden record registered." });
  } catch (error) {
    console.error("POST /api/master error:", error);
    return NextResponse.json({ error: "Failed to register product" }, { status: 500 });
  }
}
