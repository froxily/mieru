import { describe, expect, it } from "vitest";
import {
  formatCompactNumber,
  formatCurrency,
  formatMetricValue,
  formatNumber,
  formatPercent,
  formatPercentPoints,
  formatPValue,
  formatShare,
  formatSigned,
} from "./format";

describe("formatCurrency", () => {
  it("formats BRL with its symbol and magnitude-dependent precision", () => {
    expect(formatCurrency(123.45, "BRL")).toBe("R$ 123.45");
    expect(formatCurrency(15423084.73, "BRL")).toBe("R$ 15,423,085");
    expect(formatCurrency(1234.5, "BRL", { fractionDigits: 2 })).toBe("R$ 1,234.50");
  });

  it("formats millions compactly", () => {
    expect(formatCurrency(15423084.73, "BRL", { compact: true })).toBe("R$ 15.42M");
  });

  it("uses a Unicode minus before the currency symbol", () => {
    expect(formatCurrency(-123.45, "BRL")).toBe("−R$ 123.45");
  });
});

describe("formatPercent", () => {
  it("converts a ratio to a percentage with one decimal by default", () => {
    expect(formatPercent(0.0677309)).toBe("6.8%");
  });
});

describe("formatShare", () => {
  it("never rounds a non-zero share down to 0.0%", () => {
    expect(formatShare(0.0002)).toBe("<0.1%");
    expect(formatShare(0)).toBe("0.0%");
    expect(formatShare(0.254)).toBe("25.4%");
  });
});

describe("formatMetricValue", () => {
  it.each([
    [1234.6, "currency", "R$ 1,235"],
    [1234.6, "count", "1,235"],
    [0.0677309, "ratio", "6.77%"],
    [0.1677309, "ratio", "16.8%"],
    [0, "ratio", "0.0%"],
    [0.0677309, "share", "6.77%"],
    [4.156, "score", "4.16"],
    [0.7824, "index", "0.782"],
    [12.36, "days", "12.4 days"],
    [12, "days", "12 days"],
    [1234.567, "unknown", "1,234.57"],
  ])("formats %s as %s", (value, unit, expected) => {
    expect(formatMetricValue(value, unit, "BRL")).toBe(expected);
  });

  it("supports compact currency and count metrics", () => {
    expect(formatMetricValue(15423084.73, "currency", "BRL", { compact: true })).toBe("R$ 15.42M");
    expect(formatMetricValue(15423084.73, "count", undefined, { compact: true })).toBe("15.4M");
  });
});

describe("formatPValue", () => {
  it("handles zero, very small values, and ordinary p-values", () => {
    expect(formatPValue(0)).toBe("p < 1e-300");
    expect(formatPValue(0.00001)).toBe("p < 0.0001");
    expect(formatPValue(0.0318)).toBe("p = 0.0318");
    expect(formatPValue(0.0001)).toBe("p = 0.0001");
  });
});

describe("unavailable numeric values", () => {
  it.each([null, undefined, NaN])("returns an em dash for %s", (value) => {
    expect(formatNumber(value)).toBe("—");
    expect(formatCompactNumber(value)).toBe("—");
    expect(formatCurrency(value, "BRL")).toBe("—");
    expect(formatPercent(value)).toBe("—");
    expect(formatPercentPoints(value)).toBe("—");
    expect(formatSigned(value)).toBe("—");
    expect(formatPValue(value)).toBe("—");
    for (const unit of ["currency", "count", "ratio", "share", "score", "index", "days"]) {
      expect(formatMetricValue(value, unit, "BRL")).toBe("—");
    }
  });
});
