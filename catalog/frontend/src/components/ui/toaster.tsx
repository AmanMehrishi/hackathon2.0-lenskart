"use client";

import { useState, useEffect, useCallback } from "react";

export interface Toast {
  id: string;
  message: string;
  type: "success" | "error" | "info";
}

let toastListeners: ((toasts: Toast[]) => void)[] = [];
let toastQueue: Toast[] = [];

export function showToast(message: string, type: Toast["type"] = "info") {
  const id = Math.random().toString(36).slice(2);
  const toast: Toast = { id, message, type };
  toastQueue = [...toastQueue, toast];
  toastListeners.forEach((fn) => fn(toastQueue));
  setTimeout(() => {
    toastQueue = toastQueue.filter((t) => t.id !== id);
    toastListeners.forEach((fn) => fn(toastQueue));
  }, 4000);
}

export function Toaster() {
  const [toasts, setToasts] = useState<Toast[]>([]);

  useEffect(() => {
    toastListeners.push(setToasts);
    return () => {
      toastListeners = toastListeners.filter((fn) => fn !== setToasts);
    };
  }, []);

  if (toasts.length === 0) return null;

  const colors: Record<Toast["type"], string> = {
    success: "bg-emerald-600 text-white",
    error: "bg-red-600 text-white",
    info: "bg-zinc-800 text-white",
  };

  return (
    <div className="fixed bottom-6 right-6 z-50 flex flex-col gap-2">
      {toasts.map((t) => (
        <div
          key={t.id}
          className={`${colors[t.type]} rounded-lg px-4 py-3 text-sm font-medium shadow-lg animate-slide-up max-w-sm`}
        >
          {t.message}
        </div>
      ))}
    </div>
  );
}
