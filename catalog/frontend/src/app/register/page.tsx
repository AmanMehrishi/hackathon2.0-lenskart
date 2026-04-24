"use client";

import { useState, useRef, type FormEvent } from "react";
import { Upload, Loader2, ImagePlus, Database, Fingerprint } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { showToast } from "@/components/ui/toaster";

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve((reader.result as string).split(",")[1]);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

export default function RegisterPage() {
  const [loading, setLoading] = useState(false);
  const [preview, setPreview] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const fd = new FormData(form);

    const product_id = (fd.get("product_id") as string).trim();
    const brand = fd.get("brand") as string;
    const expected_price = parseFloat(fd.get("expected_price") as string);
    const category = fd.get("category") as string;
    const frame_shape = fd.get("frame_shape") as string;
    const frame_type = fd.get("frame_type") as string;
    const frame_color = fd.get("frame_color") as string;
    const imageFile = fd.get("golden_image") as File;

    if (!product_id || !brand || !expected_price || !category || !imageFile?.size) {
      showToast("Please fill in all required fields.", "error");
      return;
    }

    setLoading(true);
    try {
      const image_base64 = await fileToBase64(imageFile);
      const res = await fetch("/api/master", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          product_id, brand, expected_price, category, frame_shape, frame_type, frame_color,
          image_base64, content_type: imageFile.type || "image/jpeg",
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || `Registration failed (${res.status})`);
      }
      showToast(`Golden record "${product_id}" registered successfully.`, "success");
      form.reset();
      setPreview(null);
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Registration failed", "error");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="flex-1 p-6 md:p-10">
      <div className="mx-auto max-w-2xl">
        <div className="mb-8">
          <h1 className="text-3xl font-bold tracking-tight">Register Golden Record</h1>
          <p className="mt-2 text-zinc-500 dark:text-zinc-400">
            Define the master source-of-truth for a product. QC uploads will be compared against this record.
          </p>
        </div>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Database className="h-5 w-5" />
              Master Product Data
            </CardTitle>
            <CardDescription>
              Enter the canonical product attributes and upload the reference golden image.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit} className="space-y-6">
              <div className="space-y-2">
                <Label htmlFor="product_id">Product ID <span className="text-red-500">*</span></Label>
                <div className="relative">
                  <Fingerprint className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400" />
                  <Input id="product_id" name="product_id" placeholder="LK-AIR-5001" className="pl-10" required />
                </div>
              </div>

              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="brand">Brand <span className="text-red-500">*</span></Label>
                  <Input id="brand" name="brand" placeholder="Lenskart Air" required />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="expected_price">Expected Price ($) <span className="text-red-500">*</span></Label>
                  <Input id="expected_price" name="expected_price" type="number" step="0.01" min="0" placeholder="149.00" required />
                </div>
              </div>

              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="category">Category <span className="text-red-500">*</span></Label>
                  <Input id="category" name="category" placeholder="Eyeglasses" required />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="frame_type">Frame Type</Label>
                  <Input id="frame_type" name="frame_type" placeholder="Full Rim" />
                </div>
              </div>

              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="frame_shape">Frame Shape</Label>
                  <Input id="frame_shape" name="frame_shape" placeholder="Rectangular" />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="frame_color">Frame Color</Label>
                  <Input id="frame_color" name="frame_color" placeholder="Matte Black" />
                </div>
              </div>

              <div className="space-y-2">
                <Label>Golden Image <span className="text-red-500">*</span></Label>
                <div
                  onClick={() => fileRef.current?.click()}
                  className="group relative flex min-h-[200px] cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed border-zinc-300 bg-zinc-50 transition-colors hover:border-zinc-400 hover:bg-zinc-100 dark:border-zinc-700 dark:bg-zinc-900 dark:hover:border-zinc-600"
                >
                  {preview ? (
                    <img src={preview} alt="Preview" className="max-h-[300px] rounded-lg object-contain p-4" />
                  ) : (
                    <div className="flex flex-col items-center gap-2 text-zinc-400">
                      <ImagePlus className="h-10 w-10" />
                      <span className="text-sm font-medium">Upload the reference image</span>
                      <span className="text-xs">JPEG, PNG, WebP</span>
                    </div>
                  )}
                  <input
                    ref={fileRef} type="file" name="golden_image"
                    accept="image/jpeg,image/png,image/webp" className="hidden"
                    onChange={(e) => { const f = e.target.files?.[0]; setPreview(f ? URL.createObjectURL(f) : null); }}
                    required
                  />
                </div>
              </div>

              <Button type="submit" className="w-full" size="lg" disabled={loading}>
                {loading ? <><Loader2 className="animate-spin" /> Registering...</> : <><Upload /> Register Golden Record</>}
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>
    </main>
  );
}
