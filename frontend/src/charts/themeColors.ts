import { chartColors, sequentialBlue } from "./theme";

const darkColors: Record<string, string> = {
  [chartColors.accent]: "#4b93e8",
  [chartColors.accentDeep]: "#78b4fa",
  [chartColors.accentLight]: "#a5ceff",
  [chartColors.violet]: "#b4a0f5",
  [chartColors.ink]: "#e6ebf5",
  [chartColors.ink2]: "#b3bdd1",
  [chartColors.ink3]: "#98a5bd",
  [chartColors.surface]: "#111b2e",
  "#fff": "#111b2e",
  [chartColors.partial]: "#7f90ac",
  [chartColors.grid]: "#22304a",
  [chartColors.axis]: "#637493",
  "#104281": "#78b4fa",
};

// The heatmap ramp needs its own mapping: shared blues elsewhere are categorical.
const darkSequentialBlue = ["#17263d", "#203c5b", "#2a527c", "#33699f", "#4181c2", "#579ce4", "#7ab8f5", "#a5d3ff"];

export function themePlotColors(value: unknown, mode: "light" | "dark"): unknown {
  if (mode === "light") return value;
  if (typeof value === "string") return darkColors[value] ?? value;
  if (Array.isArray(value)) {
    const isSequentialBlue =
      value.length === sequentialBlue.length &&
      value.every(
        (stop, index) => Array.isArray(stop) && stop.length === 2 && stop[0] === sequentialBlue[index]?.[0] && stop[1] === sequentialBlue[index]?.[1],
      );
    if (isSequentialBlue) return sequentialBlue.map(([position], index) => [position, darkSequentialBlue[index]]);
    return value.map((item) => themePlotColors(item, mode));
  }
  if (value instanceof Date) return new Date(value.getTime());
  if (value instanceof ArrayBuffer) return value.slice(0);
  if (value instanceof DataView) return new DataView(value.buffer.slice(value.byteOffset, value.byteOffset + value.byteLength));
  if (ArrayBuffer.isView(value)) {
    const TypedArray = value.constructor as new (source: ArrayBufferView) => ArrayBufferView;
    return new TypedArray(value);
  }
  if (value !== null && typeof value === "object" && (Object.getPrototypeOf(value) === Object.prototype || Object.getPrototypeOf(value) === null)) {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, themePlotColors(item, mode)]));
  }
  return value;
}
