import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { getJson } from "../api/client";
import { Plot } from "../charts/Plot";
import { chartColors, sequentialBlue } from "../charts/theme";
import { formatMetricValue, formatNumber, formatPercent, formatShare } from "../lib/format";
import { Card, ChartCard } from "./Card";
import { DataTable } from "./DataTable";
import { Skeleton } from "./Skeleton";
import { Callout } from "./States";

interface Segment {
  segment: string;
  customers: number;
  customer_share: number;
  revenue: number;
  revenue_share: number | null;
  mean_recency_days: number;
  mean_frequency: number;
  mean_monetary: number;
  guidance: string;
}

interface CustomerPayload {
  available: boolean;
  reason?: string;
  currency?: string | null;
  customers?: number;
  reference_date?: string;
  orders_label?: string;
  segments?: Segment[];
  score_method?: string;
  repeat_within_horizon?: { horizon_days: number; eligible_customers: number; repeat_customers: number; rate: number; note: string } | null;
  cohorts?: { rows: { cohort: string; size: number; retention_pct: (number | null)[] }[]; periods: number[]; note: string };
  top_customers?: { customer: string; orders: number; revenue: number; recency_days: number; segment: string }[];
  reconciliation?: { segment_revenue_total: number; dashboard_label: string; dashboard_total: number | null; difference: number | null; explanation: string };
  scope_note?: string;
  redaction_note?: string;
}

function SegmentChart({ segments }: { segments: Segment[] }) {
  const data = useMemo(
    () => [
      {
        type: "bar",
        name: "Share of customers",
        x: segments.map((segment) => segment.segment),
        y: segments.map((segment) => segment.customer_share * 100),
        marker: { color: chartColors.accentLight },
        hovertemplate: "<b>%{x}</b><br>%{y:.1f}% of customers<extra></extra>",
      },
      {
        type: "bar",
        name: "Share of revenue",
        x: segments.map((segment) => segment.segment),
        y: segments.map((segment) => (segment.revenue_share ?? 0) * 100),
        marker: { color: chartColors.accentDeep },
        hovertemplate: "<b>%{x}</b><br>%{y:.1f}% of revenue<extra></extra>",
      },
    ],
    [segments],
  );
  const layout = useMemo(
    () => ({
      margin: { l: 44, r: 8, t: 36, b: 64 },
      barmode: "group",
      showlegend: true,
      legend: { orientation: "h", x: 0, y: 1, yanchor: "bottom" },
      yaxis: { ticksuffix: "%", rangemode: "tozero" },
      xaxis: { tickangle: -20 },
      bargap: 0.25,
    }),
    [],
  );
  return <Plot data={data} layout={layout} height={320} ariaLabel="RFM segments: share of customers vs share of revenue" />;
}

function CohortChart({ cohorts }: { cohorts: NonNullable<CustomerPayload["cohorts"]> }) {
  const data = useMemo(() => {
    const periods = cohorts.periods.filter((period) => period >= 1);
    const z = cohorts.rows.map((row) => periods.map((period) => row.retention_pct[period] ?? null));
    return [
      {
        type: "heatmap",
        x: periods.map((period) => `M${period}`),
        y: cohorts.rows.map((row) => `${row.cohort} · n=${formatNumber(row.size)}`),
        z,
        zmin: 0,
        colorscale: sequentialBlue,
        xgap: 2,
        ygap: 2,
        hoverongaps: false,
        text: z.map((row) => row.map((value) => (value === null ? "" : `${value.toFixed(1)}%`))),
        texttemplate: "%{text}",
        textfont: { size: 9 },
        colorbar: { thickness: 10, ticksuffix: "%", outlinewidth: 0 },
        hovertemplate: "<b>%{y}</b><br>%{x}: %{z:.1f}% bought again<extra></extra>",
      },
    ];
  }, [cohorts]);
  const layout = useMemo(
    () => ({
      margin: { l: 8, r: 8, t: 8, b: 36 },
      yaxis: { autorange: "reversed", automargin: true, tickfont: { size: 10 } },
      xaxis: { title: { text: "Months since first purchase" } },
    }),
    [],
  );
  return <Plot data={data} layout={layout} height={Math.max(260, cohorts.rows.length * 24 + 80)} ariaLabel="Acquisition cohort retention" />;
}

export function CustomerIntelligence({ endpoint, showCohorts }: { endpoint: string; showCohorts: boolean }) {
  const query = useQuery({
    queryKey: ["customer-intelligence", endpoint],
    queryFn: ({ signal }) => getJson<CustomerPayload>(endpoint, signal),
    staleTime: 120_000,
  });
  if (query.isPending) return <Skeleton height={360} style={{ borderRadius: 12 }} />;
  if (query.isError)
    return (
      <Callout tone="warning" title="Customer analytics unavailable">
        {(query.error as Error).message}
      </Callout>
    );
  const payload = query.data;
  if (!payload.available)
    return (
      <Callout tone="info" title="Customer analytics not available">
        {payload.reason}
      </Callout>
    );
  const segments = payload.segments ?? [];
  const repeat = payload.repeat_within_horizon;
  const champions = segments.find((segment) => segment.segment === "Champions");
  return (
    <div className="stack" style={{ gap: 16 }}>
      <div className="grid grid-kpi">
        <Card stagger={0}>
          <span className="kpi-label">Customers analysed</span>
          <div className="kpi-value tabular">{formatNumber(payload.customers)}</div>
          <span className="kpi-context">Recency measured to {payload.reference_date}</span>
        </Card>
        <Card stagger={1}>
          <span className="kpi-label">Repeat within {repeat?.horizon_days ?? 90} days of first order</span>
          <div className="kpi-value tabular">{repeat ? formatPercent(repeat.rate) : "—"}</div>
          <span className="kpi-context">
            {repeat
              ? `${formatNumber(repeat.repeat_customers)} of ${formatNumber(repeat.eligible_customers)} eligible customers`
              : "Too few customers with a full follow-up window"}
          </span>
        </Card>
        {champions && (
          <Card stagger={2}>
            <span className="kpi-label">Champions' share of revenue</span>
            <div className="kpi-value tabular">{formatShare(champions.revenue_share)}</div>
            <span className="kpi-context">
              from {formatNumber(champions.customers)} customers ({formatShare(champions.customer_share)})
            </span>
          </Card>
        )}
      </div>
      {repeat && <p className="text-xs muted">{repeat.note}</p>}
      <div className="grid grid-main-side">
        <ChartCard
          title="RFM segments"
          subtitle="Share of customers vs share of revenue"
          chart={<SegmentChart segments={segments} />}
          table={
            <DataTable
              rows={segments}
              rowKey={(row) => row.segment}
              columns={[
                { key: "segment", header: "Segment", render: (row) => <strong>{row.segment}</strong> },
                { key: "customers", header: "Customers", align: "right", sortValue: (row) => row.customers, render: (row) => formatNumber(row.customers) },
                {
                  key: "revenue",
                  header: "Revenue",
                  align: "right",
                  sortValue: (row) => row.revenue,
                  render: (row) => formatMetricValue(row.revenue, "currency", payload.currency),
                },
                { key: "recency", header: "Avg recency", align: "right", render: (row) => `${formatNumber(row.mean_recency_days)} d` },
                { key: "frequency", header: "Avg orders", align: "right", render: (row) => row.mean_frequency.toFixed(2) },
              ]}
            />
          }
          footer={payload.score_method}
        />
        <Card title="What to do with each segment" stagger={1}>
          <ul className="list">
            {segments.map((segment) => (
              <li key={segment.segment}>
                <strong>{segment.segment}</strong> ({formatShare(segment.customer_share)} of customers): {segment.guidance}
              </li>
            ))}
          </ul>
        </Card>
      </div>
      {showCohorts && payload.cohorts && payload.cohorts.rows.length > 1 && (
        <ChartCard
          title="Acquisition cohorts"
          subtitle={payload.cohorts.note}
          chart={<CohortChart cohorts={payload.cohorts} />}
          table={
            <DataTable
              rows={payload.cohorts.rows}
              rowKey={(row) => row.cohort}
              columns={[
                { key: "cohort", header: "Cohort" },
                { key: "size", header: "Customers", align: "right", render: (row) => formatNumber(row.size) },
                ...[1, 2, 3, 6].map((period) => ({
                  key: `m${period}`,
                  header: `M${period}`,
                  align: "right" as const,
                  render: (row: { retention_pct: (number | null)[] }) => {
                    const value = row.retention_pct[period];
                    return value === null || value === undefined ? "—" : `${value.toFixed(1)}%`;
                  },
                })),
              ]}
            />
          }
        />
      )}
      <div className="grid grid-main-side">
        <Card title="Top customers by revenue" subtitle={payload.redaction_note} stagger={2}>
          <DataTable
            rows={payload.top_customers ?? []}
            rowKey={(row) => row.customer + row.revenue}
            dense
            columns={[
              { key: "customer", header: "Customer" },
              { key: "orders", header: "Orders", align: "right", render: (row) => formatNumber(row.orders) },
              { key: "revenue", header: "Revenue", align: "right", render: (row) => formatMetricValue(row.revenue, "currency", payload.currency) },
              { key: "recency", header: "Last order", align: "right", render: (row) => `${formatNumber(row.recency_days)} d ago` },
              { key: "segment", header: "Segment" },
            ]}
          />
        </Card>
        {payload.reconciliation && (
          <Card title="Reconciliation" stagger={3}>
            <dl className="kv">
              <dt>Revenue across segments</dt>
              <dd>{formatMetricValue(payload.reconciliation.segment_revenue_total, "currency", payload.currency)}</dd>
              <dt>{payload.reconciliation.dashboard_label}</dt>
              <dd>{formatMetricValue(payload.reconciliation.dashboard_total, "currency", payload.currency)}</dd>
              <dt>Difference</dt>
              <dd>{formatMetricValue(payload.reconciliation.difference, "currency", payload.currency)}</dd>
            </dl>
            <p className="text-xs muted" style={{ marginTop: 10 }}>
              {payload.reconciliation.explanation}
            </p>
          </Card>
        )}
      </div>
      {payload.scope_note && <p className="text-xs muted">{payload.scope_note}</p>}
    </div>
  );
}
