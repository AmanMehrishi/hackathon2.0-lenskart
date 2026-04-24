"use client";

import { useState, useRef, type FormEvent } from "react";
import { Upload, Loader2, ImagePlus, DollarSign, Tag, Package } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { showToast } from "@/components/ui/toaster";

const UPLOAD_API_URL = process.env.NEXT_PUBLIC_UPLOAD_API_URL ?? "/api/upload";

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result as string;
      resolve(result.split(",")[1]);
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

export default function UploadPage() {
  const [loading, setLoading] = useState(false);
  const [preview, setPreview] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const formData = new FormData(form);

    const productName = formData.get("product_name") as string;
    const proposedPrice = parseFloat(formData.get("proposed_price") as string);
    const category = formData.get("category") as string;
    const brand = formData.get("brand") as string;
    const imageFile = formData.get("image") as File;

    if (!productName || !proposedPrice || !imageFile?.size) {
      showToast("Please fill in all required fields.", "error");
      return;
    }

    setLoading(true);

    try {
      const imageBase64 = await fileToBase64(imageFile);

      const payload = {
        image_base64: imageBase64,
        content_type: imageFile.type || "image/jpeg",
        product: {
          product_name: productName,
          proposed_price: proposedPrice,
          category,
          brand,
          attributes: {},
        },
      };

      const res = await fetch(UPLOAD_API_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || `Upload failed (${res.status})`);
      }

      const data = await res.json();
      showToast(`Product submitted! SKU: ${data.sku_id}. AI QC is evaluating.`, "success");
      form.reset();
      setPreview(null);
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Upload failed", "error");
    } finally {
      setLoading(false);
    }
  }

  function handleImageChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) {
      const url = URL.createObjectURL(file);
      setPreview(url);
    } else {
      setPreview(null);
    }
  }

  return (
    <main className="flex-1 p-6 md:p-10">
      <div className="mx-auto max-w-2xl">
        <div className="mb-8">
          <h1 className="text-3xl font-bold tracking-tight">Upload Product</h1>
          <p className="mt-2 text-zinc-500 dark:text-zinc-400">
            Submit a new product for AI-powered Quality Control evaluation.
          </p>
        </div>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Package className="h-5 w-5" />
              Product Details
            </CardTitle>
            <CardDescription>
              Fill in the product metadata and upload an image. Our multi-agent AI pipeline
              will evaluate image quality, pricing, and catalog accuracy.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit} className="space-y-6">
              {/* Product Name */}
              <div className="space-y-2">
                <Label htmlFor="product_name">
                  Product Name <span className="text-red-500">*</span>
                </Label>
                <div className="relative">
                  <Tag className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400" />
                  <Input
                    id="product_name"
                    name="product_name"
                    placeholder="Lenskart Air"
                    className="pl-10"
                    required
                  />
                </div>
              </div>

              {/* Price + Category row */}
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="proposed_price">
                    Proposed Price <span className="text-red-500">*</span>
                  </Label>
                  <div className="relative">
                    <DollarSign className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400" />
                    <Input
                      id="proposed_price"
                      name="proposed_price"
                      type="number"
                      step="0.01"
                      min="0"
                      placeholder="89.99"
                      className="pl-10"
                      required
                    />
                  </div>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="category">Category</Label>
                  <Input
                    id="category"
                    name="category"
                    placeholder="Rectangular Rimmed Glasses"
                  />
                </div>
              </div>

              {/* Brand */}
              <div className="space-y-2">
                <Label htmlFor="brand">Brand</Label>
                <Input id="brand" name="brand" placeholder="Lenskart" />
              </div>

              {/* Image Upload */}
              <div className="space-y-2">
                <Label>
                  Product Image <span className="text-red-500">*</span>
                </Label>
                <div
                  onClick={() => fileRef.current?.click()}
                  className="group relative flex min-h-[200px] cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed border-zinc-300 bg-zinc-50 transition-colors hover:border-zinc-400 hover:bg-zinc-100 dark:border-zinc-700 dark:bg-zinc-900 dark:hover:border-zinc-600"
                >
                  {preview ? (
                    <img
                      src={preview}
                      alt="Preview"
                      className="max-h-[300px] rounded-lg object-contain p-4"
                    />
                  ) : (
                    <div className="flex flex-col items-center gap-2 text-zinc-400">
                      <ImagePlus className="h-10 w-10" />
                      <span className="text-sm font-medium">Click to upload an image</span>
                      <span className="text-xs">JPEG, PNG, WebP supported</span>
                    </div>
                  )}
                  <input
                    ref={fileRef}
                    type="file"
                    name="image"
                    accept="image/jpeg,image/png,image/webp"
                    className="hidden"
                    onChange={handleImageChange}
                    required
                  />
                </div>
              </div>

              {/* Submit */}
              <Button type="submit" className="w-full" size="lg" disabled={loading}>
                {loading ? (
                  <>
                    <Loader2 className="animate-spin" />
                    Uploading &amp; Triggering QC Pipeline...
                  </>
                ) : (
                  <>
                    <Upload />
                    Submit for AI Quality Control
                  </>
                )}
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>
    </main>
  );
}
