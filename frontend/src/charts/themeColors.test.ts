import { afterEach, describe, expect, it } from "vitest";
import { baseLayout, chartColors, readChartChrome, sequentialBlue } from "./theme";
import { themePlotColors } from "./themeColors";

afterEach(() => document.documentElement.removeAttribute("style"));

describe("themePlotColors", () => {
  it("returns the exact input in light mode", () => {
    const input = { marker: { color: chartColors.ink }, colorscale: sequentialBlue };
    expect(themePlotColors(input, "light")).toBe(input);
    expect(themePlotColors(chartColors.accentDeep, "light")).toBe(chartColors.accentDeep);
  });

  it.each([
    [chartColors.accentDeep, "#78b4fa"],
    [chartColors.ink, "#e6ebf5"],
    [chartColors.ink2, "#b3bdd1"],
    [chartColors.ink3, "#98a5bd"],
    [chartColors.surface, "#111b2e"],
    ["#fff", "#111b2e"],
    [chartColors.partial, "#7f90ac"],
    [chartColors.grid, "#22304a"],
    [chartColors.axis, "#637493"],
    ["#104281", "#78b4fa"],
    ["#2a78d6", "#4b93e8"],
    ["#86b6ef", "#a5ceff"],
    [chartColors.violet, "#b4a0f5"],
  ])("maps the exact palette colour %s", (input, expected) => {
    expect(themePlotColors(input, "dark")).toBe(expected);
  });

  it("leaves unknown colours, embedded text, transparent fills and scalar values unchanged", () => {
    for (const input of ["#123456", "#184F95", "colour #184f95", "rgba(42,120,214,0.10)", chartColors.breach, chartColors.aqua, null, undefined, 0, false]) {
      expect(themePlotColors(input, "dark")).toBe(input);
    }
  });

  it("copies nested arrays and objects without mutating any inputs", () => {
    const input = Object.freeze({
      traces: Object.freeze([Object.freeze({ marker: Object.freeze({ color: Object.freeze([chartColors.ink, "#123456"]) }) })]),
      annotations: Object.freeze([Object.freeze({ font: Object.freeze({ color: chartColors.accentDeep }), text: "Revenue" })]),
    });
    const output = themePlotColors(input, "dark") as typeof input;
    expect(output).toEqual({ traces: [{ marker: { color: ["#e6ebf5", "#123456"] } }], annotations: [{ font: { color: "#78b4fa" }, text: "Revenue" }] });
    expect(output).not.toBe(input);
    expect(output.traces).not.toBe(input.traces);
    expect(output.traces[0]?.marker).not.toBe(input.traces[0]?.marker);
    expect(input.traces[0]?.marker.color[0]).toBe(chartColors.ink);
    expect(input.annotations[0]?.font.color).toBe(chartColors.accentDeep);
  });

  it("maps the full sequential ramp with increasing luminance and unchanged stops", () => {
    const original = sequentialBlue.map((stop) => [...stop]);
    const output = themePlotColors({ colorscale: sequentialBlue }, "dark") as { colorscale: [number, string][] };
    expect(output.colorscale.map(([position]) => position)).toEqual(sequentialBlue.map(([position]) => position));
    expect(output.colorscale[0]?.[1]).toBe("#17263d");
    expect(output.colorscale.at(-1)?.[1]).toBe("#a5d3ff");
    const luminances = output.colorscale.map(([, hex]) => {
      const channels = [1, 3, 5]
        .map((index) => parseInt(hex.slice(index, index + 2), 16) / 255)
        .map((v) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
      return channels[0]! * 0.2126 + channels[1]! * 0.7152 + channels[2]! * 0.0722;
    });
    luminances.slice(1).forEach((value, index) => expect(value).toBeGreaterThan(luminances[index]!));
    expect(sequentialBlue).toEqual(original);
    expect(output.colorscale[0]).not.toBe(sequentialBlue[0]);
    expect(
      themePlotColors(
        [
          [0, "#123456"],
          [1, "#654321"],
        ],
        "dark",
      ),
    ).toEqual([
      [0, "#123456"],
      [1, "#654321"],
    ]);
  });

  it("preserves dates and numeric typed arrays used by Plotly", () => {
    const input = { x: [new Date("2026-01-01")], y: new Float64Array([1, 2]) };
    const output = themePlotColors(input, "dark") as typeof input;
    expect(output).toEqual(input);
    expect(output.x[0]).not.toBe(input.x[0]);
    expect(output.y).not.toBe(input.y);
  });
});

describe("chart chrome", () => {
  it("keeps the original light fallbacks and transparent backgrounds", () => {
    expect(readChartChrome()).toEqual({
      grid: "#eef0f4",
      axis: "#d3d8e1",
      text: "#4a5366",
      muted: "#636b7d",
      hoverBg: "#0e1525",
      hoverBorder: "#0e1525",
      hoverText: "#ffffff",
    });
    expect(baseLayout()).toMatchObject({ paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)", hoverlabel: { font: { color: "#ffffff" } } });
  });

  it("reads computed CSS on every call and still merges caller overrides", () => {
    document.documentElement.style.setProperty("--chart-grid", "#22304a");
    document.documentElement.style.setProperty("--chart-text", "#b3bdd1");
    expect(baseLayout({ xaxis: { title: { text: "Sales" } } })).toMatchObject({
      font: { color: "#b3bdd1" },
      xaxis: { gridcolor: "#22304a", title: { text: "Sales", font: { color: "#b3bdd1" } } },
    });
    document.documentElement.style.setProperty("--chart-grid", "#eef0f4");
    expect(readChartChrome().grid).toBe("#eef0f4");
  });
});
