import { render, screen, within } from "@testing-library/react";
import { ShapWaterfall } from "@/components/ShapWaterfall";
import type { FeatureContribution } from "@/lib/api";

const sample: FeatureContribution[] = [
  { feature: "size_of_code", value: 1234, shap_value: -0.05 },
  { feature: "imported_dll_count", value: 8, shap_value: 0.42 },
  { feature: "max_section_entropy", value: 7.9, shap_value: -0.31 },
];

describe("ShapWaterfall", () => {
  it("sorts contributions by absolute SHAP magnitude", () => {
    render(
      <ShapWaterfall
        contributions={sample}
        baseValue={0.1}
        label="malicious"
        confidence={0.84}
      />,
    );

    // The visible <li> rows reflect the visualization order. The expected
    // order is by |shap_value| descending: 0.42, 0.31, 0.05.
    const visibleRows = screen.getAllByRole("listitem");
    const orderedFeatures = visibleRows.map((li) => {
      const features = within(li).getAllByText(
        /size_of_code|imported_dll_count|max_section_entropy/,
      );
      return features[0]?.textContent;
    });
    expect(orderedFeatures).toEqual([
      "imported_dll_count",
      "max_section_entropy",
      "size_of_code",
    ]);
  });

  it("colours bars by sign — positive (toward malicious) red, negative green", () => {
    render(
      <ShapWaterfall
        contributions={sample}
        baseValue={0}
        label="malicious"
        confidence={0.9}
      />,
    );

    // The numeric SHAP value labels carry the sign-based color class.
    // imported_dll_count has +0.42 → danger (red).
    const positive = screen.getByText("+0.420");
    expect(positive).toHaveClass("text-danger");

    // max_section_entropy has -0.31 → ok (green).
    const negative = screen.getByText("-0.310");
    expect(negative).toHaveClass("text-ok");
  });

  it("exposes a screen-reader tabular fallback", () => {
    render(
      <ShapWaterfall
        contributions={sample}
        baseValue={0}
        label="benign"
        confidence={0.6}
      />,
    );

    // The tabular fallback is rendered with `sr-only`. Querying by the
    // <caption> text is the most resilient probe — the matter is that
    // *some* table exists for screen readers.
    const caption = screen.getByText(/SHAP feature contributions for benign/i);
    expect(caption.tagName.toLowerCase()).toBe("caption");

    // All three features should appear as <td> cells in the table body.
    const table = caption.closest("table");
    expect(table).not.toBeNull();
    for (const c of sample) {
      expect(within(table!).getByText(c.feature)).toBeInTheDocument();
    }
  });

  it("renders an empty-state message when there are no contributions", () => {
    render(
      <ShapWaterfall
        contributions={[]}
        baseValue={0}
        label="benign"
        confidence={0.5}
      />,
    );
    expect(
      screen.getByText(/No SHAP contributions available/i),
    ).toBeInTheDocument();
  });
});
