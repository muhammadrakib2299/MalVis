import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ResultsPanel } from "@/components/ResultsPanel";
import { makePrediction, makeScan } from "./fixtures";

describe("ResultsPanel", () => {
  it("renders verdict rows for every prediction", () => {
    const result = makeScan({
      predictions: [
        makePrediction({ model_name: "rf-v1", label: "benign", confidence: 0.91 }),
        makePrediction({ model_name: "xgb-v1", label: "benign", confidence: 0.88 }),
      ],
    });
    render(<ResultsPanel result={result} mockMode={false} />);

    expect(screen.getByText("rf-v1")).toBeInTheDocument();
    expect(screen.getByText("xgb-v1")).toBeInTheDocument();
    expect(screen.getByText("91.0%")).toBeInTheDocument();
    expect(screen.getByText("88.0%")).toBeInTheDocument();
  });

  it("shows the mock-mode banner when /models reports mock_mode=true", () => {
    render(<ResultsPanel result={makeScan()} mockMode={true} />);
    // The banner mentions "Demo mode" — readable to a user, robust to
    // copy edits because we match a phrase, not the whole sentence.
    expect(screen.getByText(/Demo mode/i)).toBeInTheDocument();
  });

  it("hides the mock-mode banner when mockMode is false", () => {
    render(<ResultsPanel result={makeScan()} mockMode={false} />);
    expect(screen.queryByText(/Demo mode/i)).not.toBeInTheDocument();
  });

  it("highlights model disagreement when labels differ", () => {
    const result = makeScan({
      predictions: [
        makePrediction({ model_name: "rf-v1", label: "benign" }),
        makePrediction({ model_name: "xgb-v1", label: "malicious" }),
      ],
    });
    render(<ResultsPanel result={result} mockMode={false} />);
    expect(screen.getByText(/Models disagree/i)).toBeInTheDocument();
  });

  it("does not show disagreement when labels agree", () => {
    const result = makeScan({
      predictions: [
        makePrediction({ model_name: "rf-v1", label: "benign" }),
        makePrediction({ model_name: "xgb-v1", label: "benign" }),
      ],
    });
    render(<ResultsPanel result={result} mockMode={false} />);
    expect(screen.queryByText(/Models disagree/i)).not.toBeInTheDocument();
  });

  it("share button copies the permalink and shows confirmation", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { origin: "https://malvis.example" },
    });

    const result = makeScan({ sha256: "b".repeat(64) });
    render(<ResultsPanel result={result} mockMode={false} />);

    const shareButton = screen.getByRole("button", { name: /share/i });
    await userEvent.click(shareButton);

    expect(writeText).toHaveBeenCalledWith(
      `https://malvis.example/scan/${"b".repeat(64)}`,
    );
    // The button label flips to "Copied!" on success.
    expect(await screen.findByRole("button", { name: /copied/i })).toBeInTheDocument();
  });
});
