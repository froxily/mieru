import { useMemo, useState } from "react";
import type { CategoryRow, MonthlyRow, OlistOverview, PaymentRow, StateRow } from "../../api/types";
import { Plot } from "../../charts/Plot";
import { chartColors } from "../../charts/theme";
import { Card, ChartCard, Segmented } from "../../components/Card";
import { DataTable } from "../../components/DataTable";
import { ForecastCard } from "../../components/ForecastCard";
import { KpiCard } from "../../components/KpiCard";
import { useMetricDebugger } from "../../components/MetricDebugger";
import { PageHeader, SectionTitle } from "../../components/PageHeader";
import { QueryBoundary } from "../../components/QueryBoundary";
import { Callout } from "../../components/States";
import { formatCurrency, formatNumber, formatPercent, prettifyLabel } from "../../lib/format";
import { useOlistOverview } from "../../features/olist/queries";

type MonthlyMetric = "gmv" | "delivered_orders" | "average_order_value" | "active_customers";

const MONTHLY_OPTIONS: { value: MonthlyMetric; label: string }[] = [
  { value: "gmv", label: "GMV" },
  { value: "delivered_orders", label: "Orders" },
  { value: "average_order_value", label: "AOV" },
  { value: "active_customers", label: "Customers" },
];

const MONTHLY_FORMAT: Record<MonthlyMetric, { hover: string; axis: string; label: string }> = {
  gmv: { hover: "R$ %{y:,.0f}", axis: ",.2s", label: "GMV (R$)" },
  delivered_orders: { hover: "%{y:,} orders", axis: ",.0f", label: "Delivered orders" },
  average_order_value: { hover: "R$ %{y:,.2f}", axis: ",.0f", label: "AOV (R$)" },
  active_customers: { hover: "%{y:,} customers", axis: ",.0f", label: "Active customers" },
};

function MonthlyChart({ monthly, metric }: { monthly: MonthlyRow[]; metric: MonthlyMetric }) {
  const data = useMemo(
    () => [
      {
        type: "bar",
        x: monthly.map((row) => row.month),
        y: monthly.map((row) => row[metric] ?? null),
        marker: { color: monthly.map((row) => (row.is_partial ? chartColors.partial : chartColors.accent)), line: { width: 0 } },
        customdata: monthly.map((row) => (row.is_partial ? `<br><i>${row.coverage_note ?? "Partial month"}</i>` : "")),
        hovertemplate: `<b>%{x}</b><br>${MONTHLY_FORMAT[metric].hover}%{customdata}<extra></extra>`,
      },
    ],
    [monthly, metric],
  );
  const layout = useMemo(
    () => ({
      margin: { l: 56, r: 8, t: 8, b: 40 },
      yaxis: { tickformat: MONTHLY_FORMAT[metric].axis, title: { text: MONTHLY_FORMAT[metric].label } },
      xaxis: { type: "category", tickangle: -45, tickfont: { size: 10 } },
      bargap: 0.25,
    }),
    [metric],
  );
  return <Plot data={data} layout={layout} height={300} ariaLabel={`Monthly ${MONTHLY_FORMAT[metric].label}`} />;
}

function MonthlyTable({ monthly }: { monthly: MonthlyRow[] }) {
  return (
    <DataTable
      rows={monthly}
      rowKey={(row) => row.month}
      maxHeight={300}
      caption="Monthly delivered-order metrics"
      columns={[
        { key: "month", header: "Month", sortValue: (row) => row.month, render: (row) => (row.is_partial ? `${row.month} (partial)` : row.month) },
        {
          key: "delivered_orders",
          header: "Orders",
          align: "right",
          sortValue: (row) => row.delivered_orders,
          render: (row) => formatNumber(row.delivered_orders),
        },
        { key: "gmv", header: "GMV", align: "right", sortValue: (row) => row.gmv, render: (row) => formatCurrency(row.gmv, "BRL") },
        {
          key: "aov",
          header: "AOV",
          align: "right",
          sortValue: (row) => row.average_order_value,
          render: (row) => formatCurrency(row.average_order_value, "BRL", { fractionDigits: 2 }),
        },
        { key: "breach", header: "SLA breach", align: "right", sortValue: (row) => row.sla_breach_rate, render: (row) => formatPercent(row.sla_breach_rate) },
      ]}
    />
  );
}

function CategoryChart({ categories }: { categories: CategoryRow[] }) {
  const ordered = useMemo(() => [...categories].reverse(), [categories]);
  const data = useMemo(
    () => [
      {
        type: "bar",
        orientation: "h",
        y: ordered.map((row) => row.display_name),
        x: ordered.map((row) => row.gmv),
        marker: { color: chartColors.accent },
        text: ordered.map((row) => formatPercent(row.gmv_share)),
        textposition: "outside",
        textfont: { size: 11, color: chartColors.ink2 },
        cliponaxis: false,
        customdata: ordered.map((row) => [row.orders, row.mean_review_score, row.sla_breach_rate * 100]),
        hovertemplate:
          "<b>%{y}</b><br>GMV R$ %{x:,.0f}<br>Orders %{customdata[0]:,}<br>Mean review %{customdata[1]:.2f}<br>SLA breach %{customdata[2]:.1f}%<extra></extra>",
      },
    ],
    [ordered],
  );
  const layout = useMemo(
    () => ({
      margin: { l: 8, r: 48, t: 4, b: 32 },
      xaxis: { tickformat: ",.2s", title: { text: "GMV (R$)" }, showgrid: true },
      yaxis: { automargin: true, tickfont: { size: 11, color: chartColors.ink2 } },
      bargap: 0.3,
    }),
    [],
  );
  return <Plot data={data} layout={layout} height={420} ariaLabel="GMV by product category" />;
}

function StateChart({ states }: { states: StateRow[] }) {
  const top = useMemo(() => [...states].slice(0, 12).reverse(), [states]);
  const data = useMemo(
    () => [
      {
        type: "bar",
        orientation: "h",
        y: top.map((row) => `${row.state_name} (${row.customer_state})`),
        x: top.map((row) => row.gmv ?? 0),
        marker: { color: chartColors.accentDeep },
        text: top.map((row) => formatPercent(row.gmv_share ?? null)),
        textposition: "outside",
        textfont: { size: 11, color: chartColors.ink2 },
        cliponaxis: false,
        customdata: top.map((row) => [row.delivered_orders, row.sla_breach_rate * 100, row.median_delivery_days]),
        hovertemplate:
          "<b>%{y}</b><br>GMV R$ %{x:,.0f}<br>Orders %{customdata[0]:,}<br>SLA breach %{customdata[1]:.1f}%<br>Median delivery %{customdata[2]} days<extra></extra>",
      },
    ],
    [top],
  );
  const layout = useMemo(
    () => ({ margin: { l: 8, r: 48, t: 4, b: 32 }, xaxis: { tickformat: ",.2s", title: { text: "GMV (R$)" }, showgrid: true }, bargap: 0.3 }),
    [],
  );
  return <Plot data={data} layout={layout} height={420} ariaLabel="GMV by customer state" />;
}

function PaymentChart({ payments }: { payments: PaymentRow[] }) {
  const ordered = useMemo(() => [...payments].reverse(), [payments]);
  const data = useMemo(
    () => [
      {
        type: "bar",
        orientation: "h",
        y: ordered.map((row) => prettifyLabel(row.payment_type)),
        x: ordered.map((row) => row.payment_value_share * 100),
        marker: { color: chartColors.aqua },
        text: ordered.map((row) => formatPercent(row.payment_value_share)),
        textposition: "outside",
        cliponaxis: false,
        customdata: ordered.map((row) => [row.payment_value, row.orders_using_type, row.mean_installments]),
        hovertemplate:
          "<b>%{y}</b><br>Share %{x:.1f}%<br>Value R$ %{customdata[0]:,.0f}<br>Orders using type %{customdata[1]:,}<br>Mean installments %{customdata[2]:.2f}<extra></extra>",
      },
    ],
    [ordered],
  );
  const layout = useMemo(
    () => ({
      margin: { l: 8, r: 48, t: 4, b: 32 },
      xaxis: { ticksuffix: "%", range: [0, 100], title: { text: "Share of payment value" }, showgrid: true },
      bargap: 0.35,
    }),
    [],
  );
  return <Plot data={data} layout={layout} height={220} ariaLabel="Payment value share by payment type" />;
}

function OverviewContent({ data }: { data: OlistOverview }) {
  const [monthlyMetric, setMonthlyMetric] = useState<MonthlyMetric>("gmv");
  const { open } = useMetricDebugger();
  const start = data.dataset.purchase_window_start.slice(0, 10);
  const end = data.dataset.purchase_window_end.slice(0, 10);
  return (
    <div className="page">
      <PageHeader
        eyebrow="Olist marketplace · real data"
        title="Executive overview"
        description={
          <>
            Brazil's largest department-store marketplace: delivered orders purchased {start} → {end}. Every number on this page is computed from the DuckDB
            warehouse and can be traced with the <strong>ƒ</strong> button.
          </>
        }
        actions={<span className="badge">{data.dataset.currency} · GMV = price + freight</span>}
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
            status={kpi.status}
            metric={{ source: "olist", metricId: kpi.metric_id }}
            stagger={index}
          />
        ))}
      </div>

      <div className="grid grid-kpi" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))" }}>
        {data.highlights.map((highlight, index) => (
          <Card key={highlight.title} stagger={index + 4} interactive>
            <div className="highlight" style={{ padding: 0 }}>
              <span className="highlight-title">{highlight.title}</span>
              <span className="highlight-text">{highlight.text}</span>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                style={{ alignSelf: "flex-start", marginLeft: -10 }}
                onClick={() => open({ source: "olist", metricId: highlight.metric_id })}
              >
                Trace the metric →
              </button>
            </div>
          </Card>
        ))}
      </div>

      <ChartCard
        title="Monthly performance"
        subtitle="Grey bars are partial months (sparse 2016 launch period and the final snapshot month); compare complete months only."
        extraActions={<Segmented label="Monthly metric" value={monthlyMetric} options={MONTHLY_OPTIONS} onChange={setMonthlyMetric} />}
        chart={<MonthlyChart monthly={data.monthly} metric={monthlyMetric} />}
        table={<MonthlyTable monthly={data.monthly} />}
        stagger={2}
      />

      <ForecastCard endpoint="/api/olist/forecast" title="GMV forecast" />

      <SectionTitle title="Where GMV comes from" description="Category and state breakdowns reconcile exactly to platform GMV." />
      <div className="grid grid-2">
        <ChartCard
          title="Top product categories"
          subtitle={`Top 15 of ${data.categories.total_categories} categories · remaining ${data.categories.remainder.categories} = ${formatPercent(data.categories.remainder.gmv_share)} of GMV`}
          chart={<CategoryChart categories={data.categories.top} />}
          table={
            <DataTable
              rows={data.categories.top}
              rowKey={(row) => row.category}
              maxHeight={420}
              initialSort={{ key: "gmv", direction: "desc" }}
              columns={[
                { key: "display_name", header: "Category", sortValue: (row) => row.display_name },
                { key: "gmv", header: "GMV", align: "right", sortValue: (row) => row.gmv, render: (row) => formatCurrency(row.gmv, "BRL") },
                { key: "share", header: "Share", align: "right", sortValue: (row) => row.gmv_share, render: (row) => formatPercent(row.gmv_share) },
                { key: "orders", header: "Orders", align: "right", sortValue: (row) => row.orders, render: (row) => formatNumber(row.orders) },
                {
                  key: "review",
                  header: "Review",
                  align: "right",
                  sortValue: (row) => row.mean_review_score,
                  render: (row) => row.mean_review_score.toFixed(2),
                },
              ]}
            />
          }
          footer="Category names are Olist's original Portuguese labels. An order with several categories counts once in each."
        />
        <ChartCard
          title="Top customer states"
          subtitle="GMV by the customer's state · share of platform GMV"
          chart={<StateChart states={data.states} />}
          table={
            <DataTable
              rows={data.states}
              rowKey={(row) => row.customer_state}
              maxHeight={420}
              initialSort={{ key: "gmv", direction: "desc" }}
              columns={[
                { key: "state_name", header: "State", sortValue: (row) => row.state_name, render: (row) => `${row.state_name} (${row.customer_state})` },
                { key: "gmv", header: "GMV", align: "right", sortValue: (row) => row.gmv, render: (row) => formatCurrency(row.gmv ?? null, "BRL") },
                {
                  key: "orders",
                  header: "Orders",
                  align: "right",
                  sortValue: (row) => row.delivered_orders,
                  render: (row) => formatNumber(row.delivered_orders),
                },
                {
                  key: "breach",
                  header: "SLA breach",
                  align: "right",
                  sortValue: (row) => row.sla_breach_rate,
                  render: (row) => formatPercent(row.sla_breach_rate),
                },
              ]}
            />
          }
        />
      </div>

      <div className="grid grid-main-side">
        <ChartCard
          title="Payment mix"
          subtitle="Share of payment value on delivered orders"
          chart={<PaymentChart payments={data.payments} />}
          table={
            <DataTable
              rows={data.payments}
              rowKey={(row) => row.payment_type}
              columns={[
                { key: "type", header: "Type", render: (row) => prettifyLabel(row.payment_type) },
                {
                  key: "value",
                  header: "Value",
                  align: "right",
                  sortValue: (row) => row.payment_value,
                  render: (row) => formatCurrency(row.payment_value, "BRL"),
                },
                {
                  key: "orders",
                  header: "Orders using",
                  align: "right",
                  sortValue: (row) => row.orders_using_type,
                  render: (row) => formatNumber(row.orders_using_type),
                },
                {
                  key: "inst",
                  header: "Installments",
                  align: "right",
                  sortValue: (row) => row.mean_installments,
                  render: (row) => row.mean_installments.toFixed(2),
                },
              ]}
            />
          }
          footer="Payment value is a separate measure from GMV; open the Payments metric in the debugger for the reconciliation."
        />
        <Card title="What this demo shows" stagger={3}>
          <div className="stack text-sm">
            <p>
              The Olist workspace preserves a full research study (DuckDB marts, statistical tests and logistic regressions) as an interactive product
              experience.
            </p>
            <Callout tone="info" title="Honest metrics">
              GMV is not revenue: it includes freight and seller proceeds. The dataset has no cost data, so profit is shown as unavailable rather than
              estimated.
            </Callout>
            <button type="button" className="btn" onClick={() => open({ source: "olist", metricId: "olist.gross_profit" })}>
              Why is profit unavailable?
            </button>
          </div>
        </Card>
      </div>
      <p className="text-xs muted">{data.dataset.attribution}</p>
    </div>
  );
}

export function OverviewPage() {
  const query = useOlistOverview();
  return <QueryBoundary query={query}>{(data) => <OverviewContent data={data} />}</QueryBoundary>;
}
