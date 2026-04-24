import { DynamoDBClient } from "@aws-sdk/client-dynamodb";
import { DynamoDBDocumentClient } from "@aws-sdk/lib-dynamodb";

const client = new DynamoDBClient({
  region: process.env.AWS_REGION ?? "us-east-1",
});

export const docClient = DynamoDBDocumentClient.from(client, {
  marshallOptions: { removeUndefinedValues: true },
});

export const TABLE_NAME = process.env.DYNAMODB_TABLE ?? "CatalogQCTable";
export const MASTER_TABLE_NAME = process.env.DYNAMODB_MASTER_TABLE ?? "CatalogMasterTable";
export const GSI_NAME = "qc_status-created_at-index";
export const S3_BUCKET = process.env.S3_BUCKET ?? "catalog-qc-amogh-km";
