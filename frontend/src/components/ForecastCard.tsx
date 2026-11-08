import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { getJson } from "../api/client";
import { Plot } from "../charts/Plot";
import { chartColors } from "../charts/theme";
import { formatMetricValue, formatPercent } from "../lib/format";
import { Card } from "./Card";
import { Skeleton } from "./Skeleton";
import { Callout } from "./States";

interface ForecastModel {
  model: string;
  label: string;
  mae: number;
  rmse: number;
  one_step_mae: number;
  evaluation_points: number;
  skill_vs_naive: number | null;
}

interface ForecastPayload {
  available: boolean;
  reason?: string;
  granularity?: "month" | "week";
  measure?: string;
  currency?: string | null;
  history?: { period: string; value: number }[];
  forecast?: { period: string; value: number; lower: number | null; upper: number | null; step: number }[];
  selected_model?: string;
  selected_label?: string;
  models?: ForecastModel[];
  backtest?: { method: string; holdout_periods: number; horizon: number; origins: string[] };
  intervals?: { shown: boolean; level: number; method: string; reason: string | null };
  notes?: string[];
}

function ForecastChart({ payload }: { payload: ForecastPayload }) {
  const data = useMemo(() => {
    const history = payload.history ?? [];
    const forecast = payload.forecast ?? [];
    const last = history[history.length - 1];
    const forecastX = last ? [last.period, ...forecast.map((point) => point.period)] : forecast.map((point) => point.period);
    const forecastY = last ? [last.value, ...forecast.map((point) => point.value)] : forecast.map((point) => point.value);
    const traces: Record<string, unknown>[] = [
      {
        type: "scatter",
        mode: "lines+markers",
        name: "Actual",
        x: history.map((point) => point.period),
        y: history.map((point) => point.value),
        line: { color: chartColors.accent, width: 2.2 },
        marker: { size: 5, color: chartColors.accent },
        hovertemplate: "<b>%{x|%b %Y}</b><br>%{y:,.0f}<extra>Actual</extra>",
      },
      {
        type: "scatter",
        mode: "lines+markers",
        name: `Forecast · ${payload.selected_label ?? ""}`,
        x: forecastX,
        y: forecastY,
        line: { color: chartColors.breach, width: 2.2, dash: "dash" },
        marker: { size: 5, color: chartColors.breach },
        hovertemplate: "<b>%{x|%b %Y}</b><br>%{y:,.0f}<extra>Forecast</extra>",
      },
    ];
    if (payload.intervals?.shown) {
      traces.unshift({
        type: "scatter",
        mode: "lines",
        name: `${Math.round((payload.intervals.level ?? 0.8) * 100)}% interval`,
        x: [...forecast.map((point) => point.period), ...[...forecast].reverse().map((point) => point.period)],
        y: [...forecast.map((point) => point.upper), ...[...forecast].reverse().map((point) => point.lower)],
        fill: "toself",
        fillcolor: "rgba(235,104,52,0.12)",
        line: { width: 0 },
        hoverinfo: "skip",
      });
    }
    return traces;
  }, [payload]);
  const layout = useMemo(
    () => ({
      margin: { l: 64, r: 12, t: 36, b: 36 },
      showlegend: true,
      legend: { orientation: "h", x: 0, y: 1, yanchor: "bottom" },
      yaxis: { tickformat: ",.3s", rangemode: "tozero", title: { text: `${payload.measure ?? "Value"}${payload.currency ? ` (${payload.currency})` : ""}` } },
      xaxis: { type: "date", tickformat: payload.granularity === "month" ? "%b %Y" : "%d %b" },
      hovermode: "x unified",
    }),
    [payload.measure, payload.currency, payload.granularity],
  );
  return <Plot data={data} layout={layout} height={300} ariaLabel="History and forecast" />;
}

export function ForecastCard({ endpoint, title }: { endpoint: string; title: string }) {
  const query = useQuery({ queryKey: ["forecast", endpoint], queryFn: ({ signal }) => getJson<ForecastPayload>(endpoint, signal), staleTime: 120_000 });
  if (query.isPending) {
    return (
      <Card title={title} subtitle="Running the rolling-origin backtest…">
        <Skeleton height={300} />
      </Card>
    );
  }
  if (query.isError)
    return (
      <Callout tone="warning" title="Forecast unavailable">
        {(query.error as Error).message}
      </Callout>
    );
  const payload = query.data;
  if (!payload.available) {
    return (
      <Callout tone="info" title="Forecast not shown">
        {payload.reason}
      </Callout>
    );
  }
  const unit = payload.measure === "Orders" || payload.measure === "Transactions" ? "count" : "currency";
  const best = payload.models?.[0];
  return (
    <Card
      title={title}
      subtitle={`${payload.selected_label} selected by backtest MAE · ${payload.forecast?.length ?? 0} ${payload.granularity === "month" ? "months" : "weeks"} ahead`}
      footer={
        <>
          {payload.intervals?.shown
            ? `${Math.round((payload.intervals.level ?? 0.8) * 100)}% interval: ${payload.intervals.method}`
            : payload.intervals?.reason}{" "}
          {(payload.notes ?? []).join(" ")}
        </>
      }
    >
      <div className="grid grid-main-side" style={{ alignItems: "start" }}>
        <ForecastChart payload={payload} />
        <div className="stack">
          <span className="highlight-title">Backtest leaderboard</span>
          <div className="table-wrap">
            <table className="table table-dense">
              <thead>
                <tr>
                  <th>Model</th>
                  <th className="num">MAE</th>
                  <th className="num">vs naive</th>
                </tr>
              </thead>
              <tbody>
                {(payload.models ?? []).map((model) => (
                  <tr key={model.model}>
                    <td>
                      {model.model === payload.selected_model ? <strong>{model.label}</strong> : model.label}
                      {model.model === payload.selected_model && (
                        <span className="badge badge-good" style={{ marginLeft: 6 }}>
                          selected
                        </span>
                      )}
                    </td>
                    <td className="num">{formatMetricValue(model.mae, unit, payload.currency)}</td>
                    <td className="num">{model.skill_vs_naive === null ? "—" : formatPercent(model.skill_vs_naive, 0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <span className="text-xs muted">
            {payload.backtest?.method} Holdout: {payload.backtest?.holdout_periods} periods; {best?.evaluation_points} scored points per model.
          </span>
        </div>
      </div>
    </Card>
  );
}
