import { useEffect, useRef, useState } from "react";
import { baseConfig, baseLayout, type PlotRecord } from "./theme";
import { Skeleton } from "../components/Skeleton";
import { useTheme } from "../lib/theme";
import { themePlotColors } from "./themeColors";

type PlotlyModule = typeof import("plotly.js-cartesian-dist-min").default;

let plotlyLoader: Promise<PlotlyModule> | null = null;

function loadPlotly(): Promise<PlotlyModule> {
  plotlyLoader ??= import("plotly.js-cartesian-dist-min").then((module) => module.default);
  return plotlyLoader;
}

interface PlotProps {
  data: PlotRecord[];
  layout?: PlotRecord;
  config?: PlotRecord;
  height?: number;
  ariaLabel: string;
}

const EMPTY_RECORD: PlotRecord = {};

export function Plot({ data, layout = EMPTY_RECORD, config = EMPTY_RECORD, height = 320, ariaLabel }: PlotProps) {
  const { resolved } = useTheme();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const element = containerRef.current;
    if (!element) return;
    let cancelled = false;
    loadPlotly()
      .then((plotly) => {
        if (cancelled) return;
        const themedData = themePlotColors(data, resolved) as PlotRecord[];
        const themedLayout = themePlotColors(layout, resolved) as PlotRecord;
        // Resolve CSS chrome after transforming overrides: hover text and surface
        // colours have distinct roles even when their light hex values coincide.
        return plotly.react(element, themedData, baseLayout({ height, ...themedLayout }), { ...baseConfig, ...config }).then(() => {
          if (!cancelled) setReady(true);
        });
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [data, layout, config, height, resolved]);

  useEffect(() => {
    const element = containerRef.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => {
      loadPlotly()
        .then((plotly) => {
          if (element.isConnected && element.querySelector(".plot-container")) plotly.Plots.resize(element);
        })
        .catch(() => undefined);
    });
    observer.observe(element);
    return () => {
      observer.disconnect();
      loadPlotly()
        .then((plotly) => plotly.purge(element))
        .catch(() => undefined);
    };
  }, []);

  if (failed) {
    return (
      <div className="chart" style={{ height }} role="img" aria-label={ariaLabel}>
        <p className="muted text-sm">This chart could not be rendered. The data is still available in the table view.</p>
      </div>
    );
  }

  return (
    <div className="chart" style={{ height }} role="img" aria-label={ariaLabel}>
      {!ready && <Skeleton className="chart-skeleton" />}
      <div className={`chart-canvas${ready ? " ready" : ""}`}>
        <div ref={containerRef} style={{ width: "100%", height: "100%" }} />
      </div>
    </div>
  );
}
