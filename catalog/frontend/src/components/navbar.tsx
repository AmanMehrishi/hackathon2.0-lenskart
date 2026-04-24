"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, useEffect } from "react";
import { Upload, ShieldCheck, Package2, Database } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

export function Navbar() {
  const pathname = usePathname();
  const [flaggedCount, setFlaggedCount] = useState(0);

  useEffect(() => {
    async function fetchCount() {
      try {
        const res = await fetch("/api/products?status=FLAGGED_FOR_REVIEW");
        if (res.ok) {
          const data = await res.json();
          setFlaggedCount(data.count ?? 0);
        }
      } catch {
        /* silently ignore — badge just won't show */
      }
    }
    fetchCount();
    const interval = setInterval(fetchCount, 15_000);
    return () => clearInterval(interval);
  }, []);

  const links = [
    { href: "/register", label: "Register", icon: Database },
    { href: "/", label: "QC Upload", icon: Upload },
    { href: "/review", label: "Dashboard", icon: ShieldCheck, badge: flaggedCount },
  ];

  return (
    <header className="sticky top-0 z-40 border-b border-zinc-200 bg-white/80 backdrop-blur-md dark:border-zinc-800 dark:bg-zinc-950/80">
      <nav className="mx-auto flex h-16 max-w-6xl items-center justify-between px-6">
        {/* Logo */}
        <Link href="/" className="flex items-center gap-2 font-bold tracking-tight">
          <Package2 className="h-6 w-6 text-zinc-900 dark:text-zinc-100" />
          <span className="text-lg">CatalogQC</span>
        </Link>

        {/* Nav links */}
        <div className="flex items-center gap-1">
          {links.map(({ href, label, icon: Icon, badge }) => {
            const active = pathname === href;
            return (
              <Link
                key={href}
                href={href}
                className={cn(
                  "flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors",
                  active
                    ? "bg-zinc-100 text-zinc-900 dark:bg-zinc-800 dark:text-zinc-100"
                    : "text-zinc-500 hover:bg-zinc-50 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-900 dark:hover:text-zinc-100"
                )}
              >
                <Icon className="h-4 w-4" />
                {label}
                {badge !== undefined && badge > 0 && (
                  <Badge variant="destructive" className="ml-1 px-1.5 py-0 text-[10px]">
                    {badge}
                  </Badge>
                )}
              </Link>
            );
          })}
        </div>
      </nav>
    </header>
  );
}
