// Adds testing-library's matcher set (toBeInTheDocument, toHaveClass, …) to
// vitest's `expect`. Imported once per process via vitest.config.ts's
// setupFiles entry; tests don't need to repeat it.
import "@testing-library/jest-dom/vitest";

// jsdom 25 ships a Blob/File implementation but doesn't expose
// `Blob.prototype.arrayBuffer()`. Production code (UploadZone's magic-byte
// pre-check) relies on it. Polyfill via FileReader, which jsdom does
// implement and which round-trips Blob bytes deterministically.
//
// Behind a typeof guard so a future jsdom that ships the method natively
// doesn't get its built-in shadowed.
if (typeof Blob.prototype.arrayBuffer !== "function") {
  Blob.prototype.arrayBuffer = function (): Promise<ArrayBuffer> {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result as ArrayBuffer);
      reader.onerror = () => reject(reader.error);
      reader.readAsArrayBuffer(this);
    });
  };
}
