"use client";

import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import * as React from "react";

import { Button } from "@/components/ui/button";

/**
 * Two-state toggle (light ↔ dark). System-preference mode would need a
 * dropdown — kept simple until a user actually asks for it.
 *
 * The empty rendering during hydration avoids a flash where the icon
 * mismatches the resolved theme: next-themes only knows the active theme
 * after mount, so we render nothing until then.
 */
export function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  const [mounted, setMounted] = React.useState(false);

  React.useEffect(() => {
    setMounted(true);
  }, []);

  const isDark = resolvedTheme === "dark";

  return (
    <Button
      variant="ghost"
      size="icon"
      aria-label={isDark ? "Switch to light theme" : "Switch to dark theme"}
      onClick={() => setTheme(isDark ? "light" : "dark")}
    >
      {mounted ? (
        isDark ? (
          <Sun className="h-5 w-5" />
        ) : (
          <Moon className="h-5 w-5" />
        )
      ) : (
        // Reserve space pre-hydration so the nav doesn't shift.
        <span className="block h-5 w-5" aria-hidden="true" />
      )}
    </Button>
  );
}
