import { describe, expect, it } from "vitest";
import type { BridgeStep } from "../api/datasetTypes";
import { waterfallBars } from "./waterfall";

describe("waterfallBars", () => {
  it("anchors totals at zero and hangs deductions from the running total", () => {
    const steps: BridgeStep[] = [
      { label: "Gross sales", value: 500, kind: "total", metric_id: "gross_sales" },
      { label: "Discounts", value: -20, kind: "decrease", metric_id: "discounts" },
      { label: "Returns", value: -50, kind: "decrease", metric_id: "returns" },
      { label: "Net revenue", value: 430, kind: "total", metric_id: "revenue" },
      { label: "Cost", value: -352, kind: "decrease", metric_id: null },
      { label: "Gross profit", value: 78, kind: "total", metric_id: null },
    ];
    expect(waterfallBars(steps)).toEqual([
      { label: "Gross sales", base: 0, height: 500, value: 500, kind: "total" },
      { label: "Discounts", base: 480, height: 20, value: -20, kind: "decrease" },
      { label: "Returns", base: 430, height: 50, value: -50, kind: "decrease" },
      { label: "Net revenue", base: 0, height: 430, value: 430, kind: "total" },
      { label: "Cost", base: 78, height: 352, value: -352, kind: "decrease" },
      { label: "Gross profit", base: 0, height: 78, value: 78, kind: "total" },
    ]);
  });

  it("resets the running value at every total, including zero and losses", () => {
    const steps: BridgeStep[] = [
      { label: "Sales", value: 100, kind: "total", metric_id: null },
      { label: "Adjusted total", value: 40, kind: "total", metric_id: null },
      { label: "Cost", value: -60, kind: "decrease", metric_id: null },
      { label: "Loss", value: -20, kind: "total", metric_id: null },
      { label: "Reset", value: 0, kind: "total", metric_id: null },
      { label: "No deduction", value: 0, kind: "decrease", metric_id: null },
    ];
    const bars = waterfallBars(steps);
    expect(bars[2]).toMatchObject({ base: -20, height: 60 });
    expect(bars[3]).toMatchObject({ base: 0, height: -20 });
    expect(bars[5]?.base).toBe(0);
    expect(bars[5]?.height).toBeCloseTo(0);
    expect(steps[2]?.value).toBe(-60);
  });

  it("returns no bars for an empty bridge", () => {
    expect(waterfallBars([])).toEqual([]);
  });
});
