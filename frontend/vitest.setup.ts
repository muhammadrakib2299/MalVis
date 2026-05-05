// Adds testing-library's matcher set (toBeInTheDocument, toHaveClass, …) to
// vitest's `expect`. Imported once per process via vitest.config.ts's
// setupFiles entry; tests don't need to repeat it.
import "@testing-library/jest-dom/vitest";
