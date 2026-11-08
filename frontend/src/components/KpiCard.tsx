import { useEffect, useRef, useState, type CSSProperties } from "react";
import { formatMetricValue, isFiniteNumber, type MetricUnit } from "../lib/format";
import { prefersReducedMotion } from "../charts/theme";
import { useMetricDebugger, type MetricReference } from "./MetricDebugger";
import { IconFormula } from "./icons";

const COUNT_UP_MS = 520;

function useCountUp(target: number | null): number | null {
  const [display, setDisplay] = useState<number | null>(target);
  const frameRef = useRef<number | null>(null);

  useEffect(() => {
    if (!isFiniteNumber(target) || prefersReducedMotion() || document.visibilityState === "hidden") {
      setDisplay(target);
      return;
    }
    const start = performance.now();
    const step = (now: number) => {
      const progress = Math.min(1, (now - start) / COUNT_UP_MS);
      const eased = 1 - Math.pow(1 - progress, 3);
      setDisplay(target * eased);
      if (progress < 1) frameRef.current = requestAnimationFrame(step);
    };
    frameRef.current = requestAnimationFrame(step);
    const settle = window.setTimeout(() => {
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
      setDisplay(target);
    }, COUNT_UP_MS + 120);
    return () => {
      window.clearTimeout(settle);
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
    };
  }, [target]);

  return display;
}

interface KpiCardProps {
  label: string;
  value: number | null;
  unit: MetricUnit;
  currency?: string | null;
  context?: string | null;
  metric?: MetricReference;
  status?: "ok" | "unavailable";
  unavailableReason?: string | null;
  stagger?: number;
}

export function KpiCard({ label, value, unit, currency, context, metric, status = "ok", unavailableReason, stagger = 0 }: KpiCardProps) {
  const { open } = useMetricDebugger();
  const animated = useCountUp(status === "ok" ? value : null);
  const exact = formatMetricValue(value, unit, currency);
  const shown = formatMetricValue(animated, unit, currency, { compact: true });

  return (
    <section className="card card-interactive kpi" style={{ "--stagger": stagger } as CSSProperties} aria-label={label}>
      <span className="kpi-accent" aria-hidden="true" />
      <div className="kpi-top">
        <span className="kpi-label">{label}</span>
        {metric && (
          <button type="button" className="icon-btn" onClick={() => open(metric)} aria-label={`How is ${label} calculated?`} title="How is this calculated?">
            <IconFormula />
          </button>
        )}
      </div>
      {status === "ok" ? (
        <div className="kpi-value tabular" title={exact}>
          {shown}
        </div>
      ) : (
        <div className="kpi-unavailable">{unavailableReason ?? "Not available for this dataset"}</div>
      )}
      {context && <div className="kpi-context">{context}</div>}
    </section>
  );
}
