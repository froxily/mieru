import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getJson } from "../../api/client";
import type { BucketProfileRow, DayProfileRow, MonthlyRow, OlistDelivery, SimulatorResponse, StateRow } from "../../api/types";
import { Plot } from "../../charts/Plot";
import { chartColors } from "../../charts/theme";
import { Card, ChartCard, Segmented } from "../../components/Card";
import { DataTable } from "../../components/DataTable";
import { KpiCard } from "../../components/KpiCard";
import { PageHeader, SectionTitle } from "../../components/PageHeader";
import { QueryBoundary } from "../../components/QueryBoundary";
import { Callout } from "../../components/States";
import { formatNumber, formatPercent, formatPercentPoints, formatPValue, formatSigned } from "../../lib/format";
import { useOlistDelivery } from "../../features/olist/queries";

type DayMetric = "review" | "detractor";

const BUCKET_LABELS: Record<string, string> = {
  "1. >7d Early": ">7d early",
  "2. 1-7d Early": "1–7d early",
  "3. On Time (Day 0)": "On time (Day 0)",
  "4. 1-3d Late": "1–3d late",
  "5. 4-7d Late": "4–7d late",
  "6. >7d Late": ">7d late",
};

function bandTrace(xs: number[], low: (number | null)[], high: (number | null)[], color: string) {
  return {
    type: "scatter",
    mode: "lines",
    x: [...xs, ...[...xs].reverse()],
    y: [...high, ...[...low].reverse()],
    fill: "toself",
    fillcolor: color,
    line: { width: 0 },
    hoverinfo: "skip",
    showlegend: false,
  };
}

function DayCurve({ profile, metric }: { profile: DayProfileRow[]; metric: DayMetric }) {
  const data = useMemo(() => {
    const segments = [
      { rows: profile.filter((row) => row.sla_delay_days <= 0), color: chartColors.accent, band: "rgba(42,120,214,0.14)", name: "On time or early" },
      { rows: profile.filter((row) => row.sla_delay_days >= 1), color: chartColors.breach, band: "rgba(235,104,52,0.14)", name: "SLA breached" },
    ];
    return segments.flatMap((segment) => {
      const xs = segment.rows.map((row) => row.sla_delay_days);
      const values = segment.rows.map((row) => (metric === "review" ? row.review_score.mean : row.severe_detractor.rate_pct));
      const low = segment.rows.map((row) => (metric === "review" ? row.review_score.ci_low : row.severe_detractor.ci_low_pct));
      const high = segment.rows.map((row) => (metric === "review" ? row.review_score.ci_high : row.severe_detractor.ci_high_pct));
      return [
        bandTrace(xs, low, high, segment.band),
        {
          type: "scatter",
          mode: "lines+markers",
          name: segment.name,
          x: xs,
          y: values,
          line: { color: segment.color, width: 2.2, shape: "spline", smoothing: 0.4 },
          marker: { size: 7, color: segment.color, line: { color: "#fff", width: 1.5 } },
          customdata: segment.rows.map((row) => row.orders),
          hovertemplate:
            metric === "review"
              ? "<b>Day %{x}</b><br>Mean review %{y:.2f}<br>%{customdata:,} orders<extra></extra>"
              : "<b>Day %{x}</b><br>Severe detractors %{y:.1f}%<br>%{customdata:,} orders<extra></extra>",
        },
      ];
    });
  }, [profile, metric]);
  const layout = useMemo(
    () => ({
      margin: { l: 56, r: 16, t: 36, b: 44 },
      showlegend: true,
      legend: { orientation: "h", x: 0, y: 1, yanchor: "bottom" },
      xaxis: { title: { text: "Days delivered after the promised date (negative = early)" }, dtick: 3, zeroline: false },
      yaxis:
        metric === "review"
          ? { title: { text: "Mean review score" }, range: [1, 5] }
          : { title: { text: "Severe detractor rate" }, ticksuffix: "%", range: [0, 100] },
      shapes: [{ type: "line", x0: 0, x1: 0, yref: "paper", y0: 0, y1: 1, line: { color: chartColors.ink2, width: 1, dash: "dash" } }],
      annotations: [
        {
          x: 0,
          yref: "paper",
          y: 0.02,
          yanchor: "bottom",
          xanchor: "left",
          xshift: 6,
          text: "Promised date",
          showarrow: false,
          font: { size: 11, color: chartColors.ink2 },
        },
      ],
      hovermode: "closest",
    }),
    [metric],
  );
  return <Plot data={data} layout={layout} height={340} ariaLabel="Review outcome by days of SLA delay" />;
}

function BucketChart({ buckets, metric }: { buckets: BucketProfileRow[]; metric: DayMetric }) {
  const data = useMemo(() => {
    const values = buckets.map((row) => (metric === "review" ? row.review_score.mean : row.severe_detractor.rate_pct));
    const low = buckets.map((row) => (metric === "review" ? row.review_score.ci_low : row.severe_detractor.ci_low_pct));
    const high = buckets.map((row) => (metric === "review" ? row.review_score.ci_high : row.severe_detractor.ci_high_pct));
    return [
      {
        type: "bar",
        x: buckets.map((row) => BUCKET_LABELS[row.sla_delay_bucket] ?? row.sla_delay_bucket),
        y: values,
        marker: { color: buckets.map((_, index) => (index < 3 ? chartColors.accent : chartColors.breach)) },
        error_y: {
          type: "data",
          symmetric: false,
          array: values.map((value, index) => (value !== null && high[index] !== null ? (high[index] as number) - value : 0)),
          arrayminus: values.map((value, index) => (value !== null && low[index] !== null ? value - (low[index] as number) : 0)),
          color: chartColors.ink2,
          thickness: 1.2,
          width: 4,
        },
        text: values.map((value) => (value === null ? "" : metric === "review" ? value.toFixed(2) : `${value.toFixed(1)}%`)),
        textposition: "outside",
        cliponaxis: false,
        customdata: buckets.map((row) => row.orders),
        hovertemplate: `<b>%{x}</b><br>${metric === "review" ? "Mean review %{y:.2f}" : "Severe detractors %{y:.1f}%"}<br>%{customdata:,} orders<extra></extra>`,
      },
    ];
  }, [buckets, metric]);
  const layout = useMemo(
    () => ({
      margin: { l: 56, r: 8, t: 24, b: 40 },
      yaxis:
        metric === "review"
          ? { range: [0, 5.2], title: { text: "Mean review score" } }
          : { range: [0, 100], ticksuffix: "%", title: { text: "Severe detractor rate" } },
      xaxis: { type: "category" },
      bargap: 0.42,
    }),
    [metric],
  );
  return <Plot data={data} layout={layout} height={320} ariaLabel="Review outcomes by SLA delay bucket" />;
}

function MonthlyBreachChart({ monthly }: { monthly: MonthlyRow[] }) {
  const complete = useMemo(() => monthly.filter((row) => !row.is_partial), [monthly]);
  const data = useMemo(
    () => [
      {
        type: "scatter",
        mode: "lines+markers",
        x: complete.map((row) => row.month),
        y: complete.map((row) => row.sla_breach_rate * 100),
        line: { color: chartColors.breach, width: 2.2 },
        marker: { size: 6, color: chartColors.breach },
        fill: "tozeroy",
        fillcolor: "rgba(235,104,52,0.08)",
        customdata: complete.map((row) => [row.delivered_orders, row.median_delivery_days, row.median_promised_days]),
        hovertemplate:
          "<b>%{x}</b><br>SLA breach %{y:.1f}%<br>%{customdata[0]:,} orders<br>Median delivery %{customdata[1]} d vs promised %{customdata[2]} d<extra></extra>",
      },
    ],
    [complete],
  );
  const layout = useMemo(
    () => ({
      margin: { l: 48, r: 8, t: 8, b: 48 },
      yaxis: { ticksuffix: "%", rangemode: "tozero", title: { text: "SLA breach rate" } },
      xaxis: { type: "category", tickangle: -45, tickfont: { size: 10 } },
    }),
    [],
  );
  return <Plot data={data} layout={layout} height={280} ariaLabel="Monthly SLA breach rate" />;
}

function StateBreachChart({ states }: { states: StateRow[] }) {
  const ordered = useMemo(() => [...states].sort((a, b) => a.sla_breach_rate - b.sla_breach_rate), [states]);
  const data = useMemo(
    () => [
      {
        type: "bar",
        orientation: "h",
        y: ordered.map((row) => row.customer_state),
        x: ordered.map((row) => row.sla_breach_rate * 100),
        marker: { color: ordered.map((row) => (row.delivered_orders < 500 ? chartColors.partial : chartColors.breach)) },
        customdata: ordered.map((row) => [row.state_name, row.delivered_orders, row.median_delivery_days, row.median_distance_km ?? null]),
        hovertemplate:
          "<b>%{customdata[0]}</b><br>SLA breach %{x:.1f}%<br>%{customdata[1]:,} orders<br>Median delivery %{customdata[2]} days<br>Median distance %{customdata[3]:,.0f} km<extra></extra>",
      },
    ],
    [ordered],
  );
  const layout = useMemo(
    () => ({
      margin: { l: 36, r: 8, t: 4, b: 36 },
      xaxis: { ticksuffix: "%", title: { text: "SLA breach rate" }, showgrid: true },
      yaxis: { tickfont: { size: 10 } },
      bargap: 0.25,
    }),
    [],
  );
  return <Plot data={data} layout={layout} height={560} ariaLabel="SLA breach rate by customer state" />;
}

function SlaSimulator({ endpoint, baselineDelay }: { endpoint: string; baselineDelay: number }) {
  const [delayDays, setDelayDays] = useState(3);
  const [orderGmv, setOrderGmv] = useState(120);
  const [freightRatio, setFreightRatio] = useState(0.15);
  const [distanceKm, setDistanceKm] = useState(350);
  const query = useQuery({
    queryKey: ["simulator", delayDays, orderGmv, freightRatio, distanceKm],
    queryFn: ({ signal }) =>
      getJson<SimulatorResponse>(`${endpoint}?delay_days=${delayDays}&order_gmv=${orderGmv}&freight_ratio=${freightRatio}&distance_km=${distanceKm}`, signal),
    placeholderData: (previous) => previous,
  });
  const result = query.data;
  return (
    <Card title="SLA risk simulator" subtitle="Predicted probability of a 1–2 star review from the persisted Model 1 coefficients" stagger={2}>
      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))" }}>
        <div className="field">
          <label htmlFor="sim-delay">Delay vs promise: {delayDays} days</label>
          <input id="sim-delay" type="range" min={-15} max={30} value={delayDays} onChange={(event) => setDelayDays(Number(event.target.value))} />
        </div>
        <div className="field">
          <label htmlFor="sim-gmv">Order value (R$)</label>
          <input
            id="sim-gmv"
            className="input"
            type="number"
            min={1}
            max={10000}
            value={orderGmv}
            onChange={(event) => setOrderGmv(Math.max(1, Number(event.target.value) || 1))}
          />
        </div>
        <div className="field">
          <label htmlFor="sim-freight">Freight share: {formatPercent(freightRatio, 0)}</label>
          <input
            id="sim-freight"
            type="range"
            min={0}
            max={0.6}
            step={0.01}
            value={freightRatio}
            onChange={(event) => setFreightRatio(Number(event.target.value))}
          />
        </div>
        <div className="field">
          <label htmlFor="sim-distance">Distance (km)</label>
          <input
            id="sim-distance"
            className="input"
            type="number"
            min={0}
            max={5000}
            value={distanceKm}
            onChange={(event) => setDistanceKm(Math.min(5000, Math.max(0, Number(event.target.value) || 0)))}
          />
        </div>
      </div>
      <hr className="divider" style={{ margin: "16px 0" }} />
      {result ? (
        <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))" }}>
          <div className="stack" style={{ gap: 2 }}>
            <span className="kpi-label">This scenario</span>
            <span className="kpi-value tabular" style={{ color: result.scenario.is_sla_breached ? "var(--breach-ink)" : "var(--ink-1)" }}>
              {formatPercent(result.scenario.predicted_severe_detractor_probability)}
            </span>
            <span className="kpi-context">{result.scenario.is_sla_breached ? "SLA breached" : "On time or early"}</span>
          </div>
          <div className="stack" style={{ gap: 2 }}>
            <span className="kpi-label">On-time baseline ({baselineDelay} d)</span>
            <span className="kpi-value tabular">{formatPercent(result.on_time_baseline.predicted_severe_detractor_probability)}</span>
            <span className="kpi-context">{formatPercentPoints(result.absolute_risk_lift_pp)} vs baseline</span>
          </div>
          <div className="stack" style={{ gap: 2 }}>
            <span className="kpi-label">Observed at exactly {delayDays} d</span>
            <span className="kpi-value tabular">
              {result.scenario.observed_severe_detractor_rate_pct_at_this_delay === null
                ? "—"
                : `${result.scenario.observed_severe_detractor_rate_pct_at_this_delay.toFixed(1)}%`}
            </span>
            <span className="kpi-context">Empirical rate, all orders at this delay</span>
          </div>
        </div>
      ) : (
        <p className="muted text-sm">Calculating…</p>
      )}
      <p className="text-xs muted" style={{ marginTop: 12 }}>
        {result?.model_note ?? "Model 1 uses a binary breach flag: only the sign of the delay changes the prediction."}
      </p>
    </Card>
  );
}

function DeliveryContent({ data }: { data: OlistDelivery }) {
  const [dayMetric, setDayMetric] = useState<DayMetric>("detractor");
  const [bucketMetric, setBucketMetric] = useState<DayMetric>("review");
  const gap = data.review_gap;
  const model = data.adjusted_model;
  const jump = data.threshold.threshold_jump_day0_to_plus1;
  const placebo = data.threshold.placebo_jump_minus1_to_day0;
  const metricOptions: { value: DayMetric; label: string }[] = [
    { value: "detractor", label: "1–2★ rate" },
    { value: "review", label: "Mean review" },
  ];
  return (
    <div className="page">
      <PageHeader
        eyebrow="Olist marketplace · fulfilment"
        title="Delivery promise & customer reviews"
        description="How delivering after the promised date changes review scores. Breaching the promise by even one day produces a measurable review cliff; arriving early earns comparatively little."
      />
      <div className="grid grid-kpi">
        {data.kpis.map((kpi, index) => (
          <KpiCard
            key={kpi.metric_id}
            label={kpi.label}
            value={kpi.value}
            unit={kpi.unit}
            currency={kpi.currency}
            context={kpi.context}
            metric={{ source: "olist", metricId: kpi.metric_id }}
            stagger={index}
          />
        ))}
      </div>

      <div className="grid grid-3">
        <Card title="Review gap" subtitle="On time vs SLA breached (reviewed orders)" stagger={1} interactive>
          <div className="stack">
            <div className="row" style={{ alignItems: "baseline", gap: 10 }}>
              <span className="kpi-value tabular">{gap.on_time_mean.toFixed(2)}</span>
              <span className="muted">→</span>
              <span className="kpi-value tabular" style={{ color: "var(--breach-ink)" }}>
                {gap.breached_mean.toFixed(2)}
              </span>
            </div>
            <span className="text-sm muted">
              Δ {formatSigned(gap.difference)} stars (95% CI {gap.difference_ci[0].toFixed(2)} to {gap.difference_ci[1].toFixed(2)}), Welch p{" "}
              {gap.welch_p_display}
            </span>
          </div>
        </Card>
        <Card title="Severe detractors" subtitle="Share of 1–2 star reviews" stagger={2} interactive>
          <div className="stack">
            <div className="row" style={{ alignItems: "baseline", gap: 10 }}>
              <span className="kpi-value tabular">{gap.on_time_detractor_rate_pct.toFixed(1)}%</span>
              <span className="muted">→</span>
              <span className="kpi-value tabular" style={{ color: "var(--breach-ink)" }}>
                {gap.breached_detractor_rate_pct.toFixed(1)}%
              </span>
            </div>
            <span className="text-sm muted">
              Relative risk {gap.relative_risk.toFixed(2)}× (95% CI {gap.relative_risk_ci[0].toFixed(2)}–{gap.relative_risk_ci[1].toFixed(2)})
            </span>
          </div>
        </Card>
        <Card title="Adjusted odds ratio" subtitle="Logistic regression, HC0 robust SEs" stagger={3} interactive>
          <div className="stack">
            <span className="kpi-value tabular">{model.odds_ratio.toFixed(1)}×</span>
            <span className="text-sm muted">
              95% CI {model.odds_ratio_ci[0].toFixed(2)}–{model.odds_ratio_ci[1].toFixed(2)} · {formatPValue(model.p_value)} · with state + month fixed effects{" "}
              {model.fixed_effects_odds_ratio.toFixed(1)}×
            </span>
          </div>
        </Card>
      </div>

      <Callout tone="info" title="Association, not proof of causation">
        {model.caveat} Supporting evidence: a monotone dose-response across late buckets and a jump at the threshold (Day 0 → +1:{" "}
        {formatPercentPoints(jump.absolute_difference_pp)}, {jump.chi2_p_value_display.replace("< ", "p < ")}) far larger than the placebo step (Day −1 → 0:{" "}
        {formatPercentPoints(placebo.absolute_difference_pp)}, p = {placebo.chi2_p_value.toFixed(2)}). If the effect is causal, breaches account for ≈
        {formatNumber(model.excess_detractors)} extra 1–2★ reviews ({model.excess_share_pct.toFixed(1)}% of all).
      </Callout>

      <ChartCard
        title="The review cliff at the promised date"
        subtitle="Integer SLA delay from −15 to +15 days with 95% confidence bands"
        extraActions={<Segmented label="Day curve metric" value={dayMetric} options={metricOptions} onChange={setDayMetric} />}
        chart={<DayCurve profile={data.day_profile} metric={dayMetric} />}
        table={
          <DataTable
            rows={data.day_profile}
            rowKey={(row) => String(row.sla_delay_days)}
            maxHeight={340}
            columns={[
              { key: "day", header: "Delay (days)", align: "right", sortValue: (row) => row.sla_delay_days, render: (row) => String(row.sla_delay_days) },
              { key: "orders", header: "Orders", align: "right", sortValue: (row) => row.orders, render: (row) => formatNumber(row.orders) },
              {
                key: "review",
                header: "Mean review",
                align: "right",
                sortValue: (row) => row.review_score.mean,
                render: (row) => row.review_score.mean?.toFixed(2) ?? "—",
              },
              {
                key: "det",
                header: "1–2★ rate",
                align: "right",
                sortValue: (row) => row.severe_detractor.rate_pct,
                render: (row) => (row.severe_detractor.rate_pct === null ? "—" : `${row.severe_detractor.rate_pct.toFixed(1)}%`),
              },
            ]}
          />
        }
        stagger={1}
      />

      <div className="grid grid-2">
        <ChartCard
          title="Outcomes by SLA delay bucket"
          subtitle="All delivered orders, with 95% confidence intervals"
          extraActions={<Segmented label="Bucket metric" value={bucketMetric} options={metricOptions} onChange={setBucketMetric} />}
          chart={<BucketChart buckets={data.bucket_profile} metric={bucketMetric} />}
          table={
            <DataTable
              rows={data.bucket_profile}
              rowKey={(row) => row.sla_delay_bucket}
              columns={[
                { key: "bucket", header: "Bucket", render: (row) => BUCKET_LABELS[row.sla_delay_bucket] ?? row.sla_delay_bucket },
                { key: "orders", header: "Orders", align: "right", sortValue: (row) => row.orders, render: (row) => formatNumber(row.orders) },
                {
                  key: "share",
                  header: "Share",
                  align: "right",
                  sortValue: (row) => row.order_share_pct,
                  render: (row) => `${row.order_share_pct.toFixed(1)}%`,
                },
                {
                  key: "review",
                  header: "Mean review",
                  align: "right",
                  sortValue: (row) => row.review_score.mean,
                  render: (row) => row.review_score.mean?.toFixed(2) ?? "—",
                },
                {
                  key: "det",
                  header: "1–2★ rate",
                  align: "right",
                  sortValue: (row) => row.severe_detractor.rate_pct,
                  render: (row) => `${row.severe_detractor.rate_pct?.toFixed(1)}%`,
                },
              ]}
            />
          }
        />
        <SlaSimulator endpoint={data.simulator.endpoint} baselineDelay={data.simulator.baseline_delay_days} />
      </div>

      <SectionTitle title="Where and when breaches happen" description="Complete months only; states with fewer than 500 orders are shown in grey." />
      <div className="grid grid-main-side">
        <ChartCard
          title="Monthly SLA breach rate"
          subtitle="Partial months are excluded from this trend"
          chart={<MonthlyBreachChart monthly={data.monthly} />}
          table={
            <DataTable
              rows={data.monthly}
              rowKey={(row) => row.month}
              maxHeight={280}
              columns={[
                { key: "month", header: "Month", sortValue: (row) => row.month, render: (row) => (row.is_partial ? `${row.month} (partial)` : row.month) },
                {
                  key: "breach",
                  header: "SLA breach",
                  align: "right",
                  sortValue: (row) => row.sla_breach_rate,
                  render: (row) => formatPercent(row.sla_breach_rate),
                },
                {
                  key: "delivery",
                  header: "Median delivery",
                  align: "right",
                  sortValue: (row) => row.median_delivery_days,
                  render: (row) => `${row.median_delivery_days} d`,
                },
                {
                  key: "promise",
                  header: "Median promise",
                  align: "right",
                  sortValue: (row) => row.median_promised_days,
                  render: (row) => `${row.median_promised_days} d`,
                },
              ]}
            />
          }
        />
        <ChartCard
          title="SLA breach rate by state"
          subtitle="Customer state"
          chart={<StateBreachChart states={data.states} />}
          table={
            <DataTable
              rows={data.states}
              rowKey={(row) => row.customer_state}
              maxHeight={560}
              initialSort={{ key: "breach", direction: "desc" }}
              columns={[
                { key: "state", header: "State", sortValue: (row) => row.state_name, render: (row) => `${row.state_name} (${row.customer_state})` },
                {
                  key: "orders",
                  header: "Orders",
                  align: "right",
                  sortValue: (row) => row.delivered_orders,
                  render: (row) => formatNumber(row.delivered_orders),
                },
                {
                  key: "breach",
                  header: "Breach",
                  align: "right",
                  sortValue: (row) => row.sla_breach_rate,
                  render: (row) => formatPercent(row.sla_breach_rate),
                },
              ]}
            />
          }
        />
      </div>
    </div>
  );
}

export function DeliveryPage() {
  const query = useOlistDelivery();
  return <QueryBoundary query={query}>{(data) => <DeliveryContent data={data} />}</QueryBoundary>;
}
