import { useMemo } from "react";
import type { ModelSummary, OlistCustomers, RepeatBucketRow } from "../../api/types";
import { Plot } from "../../charts/Plot";
import { chartColors, sequentialBlue } from "../../charts/theme";
import { Card, ChartCard } from "../../components/Card";
import { CustomerIntelligence } from "../../components/CustomerIntelligence";
import { DataTable } from "../../components/DataTable";
import { KpiCard } from "../../components/KpiCard";
import { PageHeader, SectionTitle } from "../../components/PageHeader";
import { QueryBoundary } from "../../components/QueryBoundary";
import { Callout } from "../../components/States";
import { formatNumber, formatPValue } from "../../lib/format";
import { useOlistCustomers } from "../../features/olist/queries";

const BUCKET_LABELS: Record<string, string> = {
  "1. >7d Early": ">7d early",
  "2. 1-7d Early": "1–7d early",
  "3. On Time (Day 0)": "On time",
  "4. 1-3d Late": "1–3d late",
  "5. 4-7d Late": "4–7d late",
  "6. >7d Late": ">7d late",
};

function CohortHeatmap({ cohorts }: { cohorts: OlistCustomers["cohorts"] }) {
  const data = useMemo(() => {
    const periods = cohorts.periods.filter((period) => period >= 1);
    const z = cohorts.retention_pct.map((row) => periods.map((period) => row[period] ?? null));
    const labels = cohorts.months.map((month, index) => `${month} · n=${formatNumber(cohorts.sizes[index] ?? 0)}`);
    return [
      {
        type: "heatmap",
        x: periods.map((period) => `M${period}`),
        y: labels,
        z,
        zmin: 0,
        colorscale: sequentialBlue,
        xgap: 2,
        ygap: 2,
        hoverongaps: false,
        colorbar: { thickness: 10, ticksuffix: "%", outlinewidth: 0, tickfont: { size: 10 }, len: 0.9 },
        text: z.map((row) => row.map((value) => (value === null ? "" : `${value.toFixed(2)}%`))),
        texttemplate: "%{text}",
        textfont: { size: 9 },
        hovertemplate: "<b>Cohort %{y}</b><br>%{x}: %{z:.2f}% returned<extra></extra>",
      },
    ];
  }, [cohorts]);
  const layout = useMemo(
    () => ({
      margin: { l: 8, r: 8, t: 8, b: 36 },
      yaxis: { autorange: "reversed", tickfont: { size: 10 }, automargin: true, showgrid: false },
      xaxis: { side: "bottom", showgrid: false, title: { text: "Months since first purchase" } },
    }),
    [],
  );
  return <Plot data={data} layout={layout} height={560} ariaLabel="Monthly cohort retention heatmap" />;
}

function PooledRetentionChart({ pooled }: { pooled: OlistCustomers["cohorts"]["summary"]["pooled_retention_by_period"] }) {
  const data = useMemo(
    () => [
      {
        type: "bar",
        x: pooled.map((row) => `M${row.period_number}`),
        y: pooled.map((row) => row.pooled_retention_pct),
        marker: { color: chartColors.accent },
        customdata: pooled.map((row) => [row.active_buyers, row.cohorts_observed]),
        text: pooled.map((row) => `${row.pooled_retention_pct.toFixed(2)}%`),
        textposition: "outside",
        cliponaxis: false,
        hovertemplate: "<b>%{x}</b><br>%{y:.2f}% of buyers returned<br>%{customdata[0]:,} buyers across %{customdata[1]} cohorts<extra></extra>",
      },
    ],
    [pooled],
  );
  const layout = useMemo(() => ({ margin: { l: 44, r: 8, t: 16, b: 36 }, yaxis: { ticksuffix: "%", rangemode: "tozero" } }), []);
  return <Plot data={data} layout={layout} height={260} ariaLabel="Pooled retention by months since first purchase" />;
}

function RepeatBucketChart({ rows }: { rows: RepeatBucketRow[] }) {
  const data = useMemo(
    () => [
      {
        type: "bar",
        name: "Ever repeated (naive)",
        x: rows.map((row) => BUCKET_LABELS[row.sla_delay_bucket] ?? row.sla_delay_bucket),
        y: rows.map((row) => row.repeat_buyer.rate_pct),
        marker: { color: chartColors.partial },
        hovertemplate: "<b>%{x}</b><br>Ever repeated %{y:.2f}%<extra></extra>",
      },
      {
        type: "bar",
        name: "Repeated within 180 days of delivery",
        x: rows.map((row) => BUCKET_LABELS[row.sla_delay_bucket] ?? row.sla_delay_bucket),
        y: rows.map((row) => row.repeat_within_180d_after_first_delivery.rate_pct),
        marker: { color: chartColors.accent },
        customdata: rows.map((row) => row.repeat_within_180d_after_first_delivery.n),
        hovertemplate: "<b>%{x}</b><br>Within 180 days %{y:.2f}%<br>n = %{customdata:,} first orders<extra></extra>",
      },
    ],
    [rows],
  );
  const layout = useMemo(
    () => ({
      margin: { l: 44, r: 8, t: 36, b: 36 },
      barmode: "group",
      showlegend: true,
      legend: { orientation: "h", x: 0, y: 1, yanchor: "bottom" },
      yaxis: { ticksuffix: "%", rangemode: "tozero" },
      bargap: 0.3,
      bargroupgap: 0.08,
    }),
    [],
  );
  return <Plot data={data} layout={layout} height={300} ariaLabel="Repeat purchase rate by first-order SLA bucket" />;
}

function ModelRow({ label, model }: { label: string; model: ModelSummary }) {
  return (
    <tr>
      <td>
        <strong>{label}</strong>
        <div className="text-xs muted">{model.description}</div>
      </td>
      <td className="num">{formatNumber(model.n_obs)}</td>
      <td className="num">{formatNumber(model.n_events)}</td>
      <td className="num">
        {model.odds_ratio.toFixed(2)} [{model.odds_ratio_ci[0].toFixed(2)}, {model.odds_ratio_ci[1].toFixed(2)}]
      </td>
      <td className="num">{formatPValue(model.p_value)}</td>
      <td>{model.significant_at_5pct ? <span className="badge badge-warning">p &lt; 0.05</span> : <span className="badge">not significant</span>}</td>
    </tr>
  );
}

function CustomersContent({ data }: { data: OlistCustomers }) {
  const summary = data.cohorts.summary;
  return (
    <div className="page">
      <PageHeader
        eyebrow="Olist marketplace · customers"
        title="Customers & retention"
        description="Customers are resolved on customer_unique_id (Olist issues a new customer_id per order). Retention is structurally low on this marketplace, and the analysis reports that honestly rather than overstating it."
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
        <KpiCard
          label="Single-purchase customers"
          value={data.platform.single_purchase_share_pct / 100}
          unit="share"
          context="Bought exactly once"
          stagger={2}
        />
        <KpiCard
          label="Repeat within 180 days"
          value={data.platform.repeat_within_180d_pct / 100}
          unit="share"
          context="After first delivery, full follow-up window"
          stagger={3}
        />
      </div>

      <Callout tone="warning" title="Read retention with care">
        {data.caveat} {formatNumber(data.platform.same_day_only_repeaters)} of {formatNumber(data.platform.repeat_customers)} repeat customers placed all their
        orders on the same day (basket splits).
      </Callout>

      <div className="grid grid-main-side">
        <ChartCard
          title="Monthly acquisition cohorts"
          subtitle={`Share of each cohort buying again k months later · peak cell ${summary.peak_cell.retention_rate_pct.toFixed(2)}% · blank = not yet observable`}
          chart={<CohortHeatmap cohorts={data.cohorts} />}
          table={
            <DataTable
              rows={data.cohorts.months.map((month, index) => ({
                month,
                size: data.cohorts.sizes[index] ?? 0,
                values: data.cohorts.retention_pct[index] ?? [],
              }))}
              rowKey={(row) => row.month}
              maxHeight={560}
              columns={[
                { key: "month", header: "Cohort", sortValue: (row) => row.month },
                { key: "size", header: "Buyers", align: "right", sortValue: (row) => row.size, render: (row) => formatNumber(row.size) },
                ...[1, 2, 3, 6, 11].map((period) => ({
                  key: `m${period}`,
                  header: `M${period}`,
                  align: "right" as const,
                  render: (row: { values: (number | null)[] }) => {
                    const value = row.values[period];
                    return value === null || value === undefined ? "—" : `${value.toFixed(2)}%`;
                  },
                })),
              ]}
            />
          }
        />
        <div className="stack" style={{ gap: 16 }}>
          <ChartCard
            title="Pooled retention"
            subtitle={`All cohorts combined · ${formatNumber(summary.cohort_buyers)} buyers in ${summary.cohorts} cohorts`}
            chart={<PooledRetentionChart pooled={summary.pooled_retention_by_period} />}
            table={
              <DataTable
                rows={summary.pooled_retention_by_period}
                rowKey={(row) => String(row.period_number)}
                columns={[
                  { key: "period", header: "Month", render: (row) => `M${row.period_number}` },
                  { key: "pct", header: "Returned", align: "right", render: (row) => `${row.pooled_retention_pct.toFixed(2)}%` },
                  { key: "buyers", header: "Buyers", align: "right", render: (row) => formatNumber(row.active_buyers) },
                ]}
              />
            }
          />
          <Card title="Key retention facts" stagger={2}>
            <dl className="kv">
              <dt>Pooled month-1 retention</dt>
              <dd>{summary.pooled_month_1_retention_pct.toFixed(2)}%</dd>
              <dt>Mean cell, M1–M11</dt>
              <dd>{summary.mean_cell_retention_pct_period_1_to_11.toFixed(2)}%</dd>
              <dt>Best cohort-month</dt>
              <dd>
                {summary.peak_cell.cohort_month.slice(0, 7)} · M{summary.peak_cell.period_number} · {summary.peak_cell.retention_rate_pct.toFixed(2)}%
              </dd>
            </dl>
          </Card>
        </div>
      </div>

      <SectionTitle title="RFM segmentation" description="Recency, frequency and monetary value per customer_unique_id (GMV)." />
      <CustomerIntelligence endpoint="/api/olist/customer-intelligence" showCohorts={false} />

      <SectionTitle title="Does a late first delivery reduce repeat purchase?" description="Small effect, and not robust once follow-up time is held fixed." />
      <div className="grid grid-2">
        <ChartCard
          title="Repeat rate by first-order SLA bucket"
          subtitle="The naive 'ever repeated' rate is inflated for older (more padded-estimate) cohorts; the 180-day rate is censoring-safe."
          chart={<RepeatBucketChart rows={data.repeat_by_bucket} />}
          table={
            <DataTable
              rows={data.repeat_by_bucket}
              rowKey={(row) => row.sla_delay_bucket}
              columns={[
                { key: "bucket", header: "Bucket", render: (row) => BUCKET_LABELS[row.sla_delay_bucket] ?? row.sla_delay_bucket },
                { key: "naive", header: "Ever repeated", align: "right", render: (row) => `${row.repeat_buyer.rate_pct?.toFixed(2)}%` },
                {
                  key: "fixed",
                  header: "Within 180 d",
                  align: "right",
                  render: (row) => `${row.repeat_within_180d_after_first_delivery.rate_pct?.toFixed(2)}%`,
                },
                { key: "n", header: "n (180 d)", align: "right", render: (row) => formatNumber(row.repeat_within_180d_after_first_delivery.n) },
              ]}
            />
          }
        />
        <Card title="Retention models (first orders)" subtitle="Adjusted odds ratios, HC0 robust 95% CIs" stagger={1}>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Model</th>
                  <th className="num">n</th>
                  <th className="num">Events</th>
                  <th className="num">OR [95% CI]</th>
                  <th className="num">p</th>
                  <th>Verdict</th>
                </tr>
              </thead>
              <tbody>
                <ModelRow label="Model 2 · SLA breach" model={data.models.model_2_repeat_buyer} />
                <ModelRow label="Model 2b · 1–2★ review" model={data.models.model_2b_detractor_exposure} />
                <ModelRow label="Model 2c · 180-day horizon" model={data.models.model_2c_fixed_horizon} />
              </tbody>
            </table>
          </div>
          <p className="text-xs muted" style={{ marginTop: 12 }}>
            Model 2c is the defensible estimate: it fixes the follow-up window, removing the right-censoring bias that inflates Model 2.
          </p>
        </Card>
      </div>
    </div>
  );
}

export function CustomersPage() {
  const query = useOlistCustomers();
  return <QueryBoundary query={query}>{(data) => <CustomersContent data={data} />}</QueryBoundary>;
}
