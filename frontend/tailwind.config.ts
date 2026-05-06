import type { Config } from "tailwindcss";

// Theme model
//
// Surface chrome (ink/surface/border) and the shadcn primitives
// (background/foreground/card/muted/...) are CSS-variable-driven so they
// switch with the active theme. Brand/semantic accents (accent/warn/danger/ok)
// stay fixed so a "danger" pill reads as danger in either theme.
//
// The ink/surface/border aliases are kept so existing components keep
// rendering during the migration to shadcn primitives — they map to the
// same variables Card/Button/etc. read from.

const config: Config = {
  darkMode: ["class"],
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // shadcn primitives
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        ring: "hsl(var(--ring))",
        // Legacy aliases — bound to the same variables for migration safety.
        ink: "hsl(var(--background))",
        surface: "hsl(var(--card))",
        border: "hsl(var(--border))",
        // Brand + semantic accents stay fixed.
        accent: "#5eb1ff",
        warn: "#f0b429",
        danger: "#f04438",
        ok: "#22c55e",
      },
      fontFamily: {
        sans: ["ui-sans-serif", "system-ui", "Segoe UI", "Helvetica Neue", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
    },
  },
  plugins: [],
};

export default config;
