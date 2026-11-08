import type { BridgeStep } from "../api/datasetTypes";

export function waterfallBars(steps: BridgeStep[]): { label: string; base: number; height: number; value: number; kind: BridgeStep["kind"] }[] {
  let running = 0;
  return steps.map(({ label, value, kind }) => {
    if (kind === "total") {
      running = value;
      return { label, base: 0, height: value, value, kind };
    }
    running += value;
    return { label, base: running, height: -value, value, kind };
  });
}
