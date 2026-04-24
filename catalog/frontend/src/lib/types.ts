export interface Product {
  sku_id: string;
  product_name: string;
  proposed_price: number | string;
  category?: string;
  brand?: string;
  attributes?: Record<string, unknown>;
  s3_image_url: string;
  qc_status: "PENDING" | "APPROVED" | "REJECTED" | "FLAGGED_FOR_REVIEW";
  qc_flags: string[];
  reasoning?: string[];
  confidence_score?: number;
  fashion_score: number;
  created_at: string;
  qc_completed_at?: string;
}
