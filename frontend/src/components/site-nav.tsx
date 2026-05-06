import Link from "next/link";
import { ShieldCheck } from "lucide-react";

import { ThemeToggle } from "@/components/theme-toggle";

/**
 * Sticky top nav shared by the home page and the /scan/[hash] permalink.
 *
 * Translucent + backdrop-blur on browsers that support it; opaque fallback
 * elsewhere so the nav stays legible over scrolled content either way.
 */
export function SiteNav() {
  return (
    <header className="sticky top-0 z-40 border-b border-border bg-background/80 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-6">
        <Link
          href="/"
          className="flex items-center gap-2 font-semibold tracking-tight"
        >
          <ShieldCheck className="h-5 w-5 text-primary" aria-hidden />
          <span>MalVis</span>
        </Link>
        <ThemeToggle />
      </div>
    </header>
  );
}
