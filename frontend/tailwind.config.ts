import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Brand palette — kept small until the design pass in Phase 5.
        ink: "#0e1116",
        surface: "#161b22",
        border: "#30363d",
        accent: "#5eb1ff",
        warn: "#f0b429",
        danger: "#f04438",
        ok: "#22c55e",
      },
      fontFamily: {
        // System stack — the dashboard is meant to look like a tool, not a brochure.
        sans: ["ui-sans-serif", "system-ui", "Segoe UI", "Helvetica Neue", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
