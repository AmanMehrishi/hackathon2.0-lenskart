"use client";

import { useState, useEffect, useCallback } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  XCircle,
  RefreshCw,
  Loader2,
  Sparkles,
  DollarSign,
  Image as ImageIcon,
  ShieldCheck,
  ShieldX,
  ShieldQuestion,
  Gauge,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { showToast } from "@/components/ui/toaster";
import { cn } from "@/lib/utils";
import type { Product } from "@/lib/types";

type TabKey = "FLAGGED_FOR_REVIEW" | "APPROVED" | "REJECTED";

const TABS: { key: TabKey; label: string; icon: typeof ShieldCheck }[] = [
  { key: "FLAGGED_FOR_REVIEW", label: "Flagged", icon: ShieldQuestion },
  { key: "APPROVED", label: "Passed", icon: ShieldCheck },
  { key: "REJECTED", label: "Rejected", icon: ShieldX },
];

function confidenceColor(score: number) {
  if (score >= 85) return "text-emerald-600 bg-emerald-50 dark:text-emerald-400 dark:bg-emerald-950/40";
  if (score >= 60) return "text-amber-600 bg-amber-50 dark:text-amber-400 dark:bg-amber-950/40";
  return "text-red-600 bg-red-50 dark:text-red-400 dark:bg-red-950/40";
}

function statusBadge(status: string) {
  switch (status) {
    case "APPROVED":
      return <Badge variant="success"><CheckCircle2 className="mr-1 h-3 w-3" />Approved</Badge>;
    case "REJECTED":
      return <Badge variant="destructive"><XCircle className="mr-1 h-3 w-3" />Rejected</Badge>;
    default:
      return <Badge variant="warning"><AlertTriangle className="mr-1 h-3 w-3" />Flagged</Badge>;
  }
}

export default function ReviewPage() {
  const [activeTab, setActiveTab] = useState<TabKey>("FLAGGED_FOR_REVIEW");
  const [products, setProducts] = useState<Product[]>([]);
  const [counts, setCounts] = useState<Record<TabKey, number>>({ FLAGGED_FOR_REVIEW: 0, APPROVED: 0, REJECTED: 0 });
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState<Record<string, boolean>>({});

  const fetchTab = useCallback(async (tab: TabKey) => {
    setLoading(true);
    try {
      const res = await fetch(`/api/products?status=${tab}`);
      if (!res.ok) throw new Error("Fetch failed");
      const data = await res.json();
      setProducts(data.products ?? []);
      setCounts((prev) => ({ ...prev, [tab]: data.count ?? 0 }));
    } catch {
      showToast("Failed to load products.", "error");
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchAllCounts = useCallback(async () => {
    for (const tab of TABS) {
      try {
        const res = await fetch(`/api/products?status=${tab.key}`);
        if (res.ok) {
          const data = await res.json();
          setCounts((prev) => ({ ...prev, [tab.key]: data.count ?? 0 }));
        }
      } catch { /* ignore */ }
    }
  }, []);

  useEffect(() => {
    fetchTab(activeTab);
    fetchAllCounts();
  }, [activeTab, fetchTab, fetchAllCounts]);

  async function handleAction(skuId: string, newStatus: "APPROVED" | "REJECTED") {
    setActionLoading((prev) => ({ ...prev, [skuId]: true }));
    setProducts((prev) => prev.filter((p) => p.sku_id !== skuId));
    setCounts((prev) => ({ ...prev, [activeTab]: Math.max(0, prev[activeTab] - 1) }));

    try {
      const res = await fetch("/api/products", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sku_id: skuId, new_status: newStatus }),
      });
      if (!res.ok) throw new Error("Update failed");
      showToast(`${skuId} → ${newStatus.toLowerCase()}.`, "success");
    } catch {
      showToast("Failed to update.", "error");
      fetchTab(activeTab);
    } finally {
      setActionLoading((prev) => ({ ...prev, [skuId]: false }));
    }
  }

  const showActions = activeTab === "FLAGGED_FOR_REVIEW";

  return (
    <main className="flex-1 p-6 md:p-10">
      <div className="mx-auto max-w-6xl">
        {/* Header */}
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold tracking-tight">QC Dashboard</h1>
            <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
              AI-evaluated catalog items with confidence-based straight-through processing.
            </p>
          </div>
          <Button variant="outline" size="sm" onClick={() => { fetchTab(activeTab); fetchAllCounts(); }} disabled={loading}>
            <RefreshCw className={loading ? "animate-spin" : ""} />
            Refresh
          </Button>
        </div>

        {/* Tabs */}
        <div className="mb-6 flex gap-1 rounded-xl bg-zinc-100 p-1 dark:bg-zinc-900">
          {TABS.map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              onClick={() => setActiveTab(key)}
              className={cn(
                "flex flex-1 items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-medium transition-all",
                activeTab === key
                  ? "bg-white text-zinc-900 shadow-sm dark:bg-zinc-800 dark:text-zinc-100"
                  : "text-zinc-500 hover:text-zinc-700 dark:text-zinc-400 dark:hover:text-zinc-200"
              )}
            >
              <Icon className="h-4 w-4" />
              {label}
              {counts[key] > 0 && (
                <span className={cn(
                  "ml-1 rounded-full px-2 py-0.5 text-xs font-bold",
                  key === "FLAGGED_FOR_REVIEW" ? "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-400"
                    : key === "APPROVED" ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-400"
                    : "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400"
                )}>
                  {counts[key]}
                </span>
              )}
            </button>
          ))}
        </div>

        {/* Loading */}
        {loading && (
          <div className="flex flex-col items-center justify-center py-20 text-zinc-400">
            <Loader2 className="h-10 w-10 animate-spin" />
            <p className="mt-4 text-sm">Loading...</p>
          </div>
        )}

        {/* Empty */}
        {!loading && products.length === 0 && (
          <div className="flex flex-col items-center justify-center rounded-xl border-2 border-dashed border-zinc-200 py-20 dark:border-zinc-800">
            <CheckCircle2 className="h-12 w-12 text-emerald-500" />
            <p className="mt-4 text-lg font-medium">Nothing here</p>
            <p className="mt-1 text-sm text-zinc-500">
              No products with status &quot;{activeTab.replace(/_/g, " ").toLowerCase()}&quot;.
            </p>
          </div>
        )}

        {/* Cards */}
        {!loading && products.length > 0 && (
          <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {products.map((product) => {
              const confidence = product.confidence_score ?? 0;
              const reasons = product.reasoning ?? product.qc_flags ?? [];

              return (
                <Card key={product.sku_id} className="flex flex-col overflow-hidden">
                  {/* Image */}
                  <div className="relative aspect-[4/3] bg-zinc-100 dark:bg-zinc-900">
                    {product.s3_image_url ? (
                      <img
                        src={product.s3_image_url}
                        alt={product.product_name}
                        className="h-full w-full object-contain p-2"
                        onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
                      />
                    ) : (
                      <div className="flex h-full items-center justify-center">
                        <ImageIcon className="h-12 w-12 text-zinc-300" />
                      </div>
                    )}
                    <div className="absolute right-3 top-3">{statusBadge(product.qc_status)}</div>
                  </div>

                  <CardHeader className="pb-2">
                    <div className="flex items-start justify-between gap-2">
                      <CardTitle className="line-clamp-2 text-base">{product.product_name}</CardTitle>
                      <div className="flex shrink-0 items-center gap-1 text-sm font-semibold">
                        <DollarSign className="h-3.5 w-3.5" />
                        {Number(product.proposed_price).toFixed(2)}
                      </div>
                    </div>
                    <p className="text-xs text-zinc-400">{product.sku_id}</p>
                  </CardHeader>

                  <CardContent className="flex-1 space-y-3 pb-4">
                    {/* Scores row */}
                    <div className="flex items-center gap-3">
                      {/* Confidence */}
                      <div className={cn("flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-bold", confidenceColor(confidence))}>
                        <Gauge className="h-3.5 w-3.5" />
                        {confidence}%
                      </div>
                      {/* Fashion */}
                      {product.fashion_score > 0 && (
                        <div className="flex items-center gap-1.5 rounded-md bg-violet-50 px-2.5 py-1 text-xs font-bold text-violet-700 dark:bg-violet-950/40 dark:text-violet-400">
                          <Sparkles className="h-3.5 w-3.5" />
                          {product.fashion_score}/10
                        </div>
                      )}
                    </div>

                    {/* Reasoning */}
                    {reasons.length > 0 && (
                      <div className="space-y-1.5">
                        <p className="text-xs font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
                          AI Reasoning
                        </p>
                        <ul className="space-y-1">
                          {reasons.map((reason, i) => (
                            <li
                              key={i}
                              className="flex items-start gap-2 rounded-md bg-zinc-50 px-3 py-2 text-xs text-zinc-700 dark:bg-zinc-900 dark:text-zinc-300"
                            >
                              <span className="mt-0.5 shrink-0 text-zinc-400">{i + 1}.</span>
                              {reason}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </CardContent>

                  {showActions && (
                    <CardFooter className="flex-wrap gap-2 border-t border-zinc-100 pt-4 dark:border-zinc-800">
                      <Button
                        variant="success"
                        size="sm"
                        className="min-w-[100px] flex-1"
                        disabled={!!actionLoading[product.sku_id]}
                        onClick={() => handleAction(product.sku_id, "APPROVED")}
                      >
                        {actionLoading[product.sku_id] ? <Loader2 className="animate-spin" /> : <CheckCircle2 />}
                        Approve
                      </Button>
                      <Button
                        variant="destructive"
                        size="sm"
                        className="min-w-[100px] flex-1"
                        disabled={!!actionLoading[product.sku_id]}
                        onClick={() => handleAction(product.sku_id, "REJECTED")}
                      >
                        {actionLoading[product.sku_id] ? <Loader2 className="animate-spin" /> : <XCircle />}
                        Reject
                      </Button>
                    </CardFooter>
                  )}
                </Card>
              );
            })}
          </div>
        )}
      </div>
    </main>
  );
}
