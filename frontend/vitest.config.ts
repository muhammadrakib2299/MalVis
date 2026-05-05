/// <reference types="vitest" />
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

// jsdom env so React Testing Library has a DOM. globals=true means
// describe/it/expect work without imports — matches the pytest-style
// test ergonomics already in the backend suite.
//
// The `@/` path alias mirrors `tsconfig.json::compilerOptions.paths` so
// component imports work identically inside tests and inside src/.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    include: ["tests/**/*.test.{ts,tsx}"],
    css: false, // Tailwind class strings are noise during unit tests.
  },
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
});
