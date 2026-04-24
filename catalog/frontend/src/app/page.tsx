"use client";

import { useState, useRef, type FormEvent } from "react";
import { Upload, Loader2, ImagePlus, Fingerprint, ScanLine } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { showToast } from "@/components/ui/toaster";

const UPLOAD_API_URL = process.env.NEXT_PUBLIC_UPLOAD_API_URL ?? "/api/upload";

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve((reader.result as string).split(",")[1]);
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
    const fd = new FormData(form);

    const product_id = (fd.get("product_id") as string).trim();
    const proposed_price = parseFloat(fd.get("proposed_price") as string);
    const imageFile = fd.get("qc_image") as File;

    if (!product_id || !imageFile?.size) {
      showToast("Please enter a Product ID and upload an image.", "error");
      return;
    }

    setLoading(true);
    try {
      const imageBase64 = await fileToBase64(imageFile);

      const res = await fetch(UPLOAD_API_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          image_base64: imageBase64,
          content_type: imageFile.type || "image/jpeg",
          product_id,
          proposed_price: isNaN(proposed_price) ? 0 : proposed_price,
        }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || `Upload failed (${res.status})`);
      }

      const data = await res.json();
      showToast(`QC submitted! Upload ID: ${data.sku_id}. AI pipeline running.`, "success");
      form.reset();
      setPreview(null);
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Upload failed", "error");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="flex-1 p-6 md:p-10">
      <div className="mx-auto max-w-2xl">
        <div className="mb-8">
          <h1 className="text-3xl font-bold tracking-tight">QC Upload</h1>
          <p className="mt-2 text-zinc-500 dark:text-zinc-400">
            Submit a product image for AI quality control. Metadata is pulled from the Golden Record automatically.
          </p>
        </div>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ScanLine className="h-5 w-5" />
              Quality Check Submission
            </CardTitle>
            <CardDescription>
              Enter the registered Product ID and upload the vendor&apos;s QC image.
              The pipeline will compare it against the master golden record.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit} className="space-y-6">
              <div className="space-y-2">
                <Label htmlFor="product_id">
                  Product ID <span className="text-red-500">*</span>
                </Label>
                <div className="relative">
                  <Fingerprint className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400" />
                  <Input
                    id="product_id" name="product_id"
                    placeholder="LK-AIR-5001"
                    className="pl-10" required
                  />
                </div>
                <p className="text-xs text-zinc-400">Must match a registered golden record.</p>
              </div>

              <div className="space-y-2">
                <Label htmlFor="proposed_price">Proposed Price ($)</Label>
                <Input
                  id="proposed_price" name="proposed_price"
                  type="number" step="0.01" min="0"
                  placeholder="149.00"
                />
                <p className="text-xs text-zinc-400">Vendor&apos;s listed price. Compared against master expected price.</p>
              </div>

              <div className="space-y-2">
                <Label>QC Image <span className="text-red-500">*</span></Label>
                <div
                  onClick={() => fileRef.current?.click()}
                  className="group relative flex min-h-[200px] cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed border-zinc-300 bg-zinc-50 transition-colors hover:border-zinc-400 hover:bg-zinc-100 dark:border-zinc-700 dark:bg-zinc-900 dark:hover:border-zinc-600"
                >
                  {preview ? (
                    <img src={preview} alt="Preview" className="max-h-[300px] rounded-lg object-contain p-4" />
                  ) : (
                    <div className="flex flex-col items-center gap-2 text-zinc-400">
                      <ImagePlus className="h-10 w-10" />
                      <span className="text-sm font-medium">Upload the vendor&apos;s product image</span>
                      <span className="text-xs">JPEG, PNG, WebP</span>
                    </div>
                  )}
                  <input
                    ref={fileRef} type="file" name="qc_image"
                    accept="image/jpeg,image/png,image/webp" className="hidden"
                    onChange={(e) => { const f = e.target.files?.[0]; setPreview(f ? URL.createObjectURL(f) : null); }}
                    required
                  />
                </div>
              </div>

              <Button type="submit" className="w-full" size="lg" disabled={loading}>
                {loading ? <><Loader2 className="animate-spin" /> Running AI QC Pipeline...</> : <><Upload /> Submit for QC</>}
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>
    </main>
  );
}
