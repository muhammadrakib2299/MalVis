import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { UploadZone } from "@/components/UploadZone";
import { makeScan } from "./fixtures";

// Mock the API client. `postScan` is the only function UploadZone touches;
// we control its return value per test rather than spinning up a fetch
// stub that simulates the real backend.
const postScanMock = vi.fn();
vi.mock("@/lib/api", async () => {
  // Keep the real ApiError class so the catch arm in UploadZone behaves
  // exactly as it does in production. Only `postScan` is replaced.
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    postScan: (...args: unknown[]) => postScanMock(...args),
  };
});

function makePeFile(prefix: number[], totalBytes: number, name = "sample.exe"): File {
  const bytes = new Uint8Array(totalBytes);
  bytes.set(prefix, 0);
  return new File([bytes], name, { type: "application/octet-stream" });
}

describe("UploadZone", () => {
  beforeEach(() => {
    postScanMock.mockReset();
  });

  it("rejects a file that doesn't start with MZ before posting", async () => {
    const onResult = vi.fn();
    render(<UploadZone onResult={onResult} />);

    // PNG magic bytes — clearly not a PE.
    const notPe = makePeFile([0x89, 0x50, 0x4e, 0x47], 256, "image.png");
    // The visible <input> is `class="hidden"`, but testing-library's
    // userEvent.upload still drives it via the DOM node. Query by type
    // rather than label/role since the input is intentionally hidden.
    const fileInput = document.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    await userEvent.upload(fileInput, notPe);

    expect(onResult).not.toHaveBeenCalled();
    expect(postScanMock).not.toHaveBeenCalled();
    expect(
      screen.getByText(/missing MZ magic/i),
    ).toBeInTheDocument();
  });

  it("rejects an oversize file before posting", async () => {
    const onResult = vi.fn();
    render(<UploadZone onResult={onResult} />);

    // 11 MB — over the 10 MB client-side cap.
    const oversize = makePeFile([0x4d, 0x5a], 11 * 1024 * 1024);
    const fileInput = document.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    await userEvent.upload(fileInput, oversize);

    expect(onResult).not.toHaveBeenCalled();
    expect(postScanMock).not.toHaveBeenCalled();
    expect(screen.getByText(/exceeds the 10 MB limit/i)).toBeInTheDocument();
  });

  it("rejects an empty file", async () => {
    const onResult = vi.fn();
    render(<UploadZone onResult={onResult} />);

    const empty = new File([], "empty.exe", { type: "application/octet-stream" });
    const fileInput = document.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    await userEvent.upload(fileInput, empty);

    expect(onResult).not.toHaveBeenCalled();
    expect(screen.getByText(/file is empty/i)).toBeInTheDocument();
  });

  it("posts a valid PE and hands the result to the callback", async () => {
    const result = makeScan();
    postScanMock.mockResolvedValue(result);

    const onResult = vi.fn();
    render(<UploadZone onResult={onResult} />);

    // Minimal MZ-prefixed file. The client-side check passes; the mocked
    // postScan returns our fixture without touching the network.
    const validPe = makePeFile([0x4d, 0x5a], 1024);
    const fileInput = document.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    await userEvent.upload(fileInput, validPe);

    // The validation chain (slice + arrayBuffer + magic-byte check) and the
    // postScan call are async, and userEvent.upload resolves before those
    // microtasks flush — assert via waitFor so the test waits for the
    // post-validation network call to land.
    await waitFor(() => expect(postScanMock).toHaveBeenCalledTimes(1));
    expect(postScanMock).toHaveBeenCalledWith(validPe);

    // Callback received (result, file).
    await waitFor(() =>
      expect(onResult).toHaveBeenCalledWith(result, validPe),
    );
  });
});
