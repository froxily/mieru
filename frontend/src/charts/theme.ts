export type PlotRecord = Record<string, unknown>;

export const chartColors = {
  accent: "#2a78d6",
  accentDeep: "#184f95",
  accentLight: "#86b6ef",
  breach: "#eb6834",
  aqua: "#1baf7a",
  violet: "#4a3aa7",
  ink: "#0e1525",
  ink2: "#4a5366",
  ink3: "#636b7d",
  grid: "#eef0f4",
  axis: "#d3d8e1",
  surface: "#ffffff",
  partial: "#c3c9d4",
} as const;

export const sequentialBlue: [number, string][] = [
  [0, "#f3f8fe"],
  [0.14, "#cde2fb"],
  [0.28, "#9ec5f4"],
  [0.43, "#6da7ec"],
  [0.57, "#3987e5"],
  [0.71, "#256abf"],
  [0.86, "#184f95"],
  [1, "#0d366b"],
];

const FONT_FAMILY = '"Segoe UI Variable Text", "Segoe UI", system-ui, -apple-system, "Helvetica Neue", Arial, sans-serif';

function isPlainObject(value: unknown): value is PlotRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function deepMerge(base: PlotRecord, overrides: PlotRecord): PlotRecord {
  const result: PlotRecord = { ...base };
  for (const [key, value] of Object.entries(overrides)) {
    const existing = result[key];
    result[key] = isPlainObject(existing) && isPlainObject(value) ? deepMerge(existing, value) : value;
  }
  return result;
}

export function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function" ? window.matchMedia("(prefers-reduced-motion: reduce)").matches : true;
}

export function readChartChrome() {
  const styles = typeof document !== "undefined" ? getComputedStyle(document.documentElement) : undefined;
  const read = (name: string, fallback: string) => styles?.getPropertyValue(name).trim() || fallback;
  return {
    grid: read("--chart-grid", chartColors.grid),
    axis: read("--chart-axis", chartColors.axis),
    text: read("--chart-text", chartColors.ink2),
    muted: read("--chart-text-muted", chartColors.ink3),
    hoverBg: read("--chart-hover-bg", chartColors.ink),
    hoverBorder: read("--chart-hover-border", chartColors.ink),
    hoverText: read("--chart-hover-text", "#ffffff"),
  };
}

export function baseLayout(overrides: PlotRecord = {}): PlotRecord {
  const chrome = readChartChrome();
  const axis = {
    gridcolor: chrome.grid,
    linecolor: chrome.axis,
    tickcolor: chrome.axis,
    zeroline: false,
    automargin: true,
    tickfont: { size: 11, color: chrome.muted },
    title: { font: { size: 12, color: chrome.text }, standoff: 10 },
  };
  return deepMerge(
    {
      font: { family: FONT_FAMILY, size: 12, color: chrome.text },
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      margin: { l: 8, r: 12, t: 8, b: 8, pad: 4 },
      hoverlabel: {
        bgcolor: chrome.hoverBg,
        bordercolor: chrome.hoverBorder,
        font: { family: FONT_FAMILY, size: 12, color: chrome.hoverText },
        align: "left",
      },
      xaxis: { ...axis, showline: true, ticks: "outside", ticklen: 4, showgrid: false },
      yaxis: { ...axis, showline: false, ticks: "" },
      legend: { orientation: "h", x: 0, y: 1.12, font: { size: 12, color: chrome.text }, bgcolor: "rgba(0,0,0,0)" },
      bargap: 0.38,
      showlegend: false,
      transition: prefersReducedMotion() ? { duration: 0 } : { duration: 280, easing: "cubic-in-out" },
    },
    overrides,
  );
}

export const baseConfig: PlotRecord = {
  displayModeBar: false,
  responsive: true,
  displaylogo: false,
  scrollZoom: false,
};
