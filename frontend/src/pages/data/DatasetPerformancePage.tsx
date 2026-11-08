import { useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import type {
  Concentration,
  DatasetFilters,
  DatasetPerformance,
  DiscountsAnalysis,
  ParetoSummary,
  PerformanceDimension,
  Profitability,
  ReturnsAnalysis,
  RevenueBridge,
  Unavailable,
} from "../../api/datasetTypes";
import { Plot } from "../../charts/Plot";
import { chartColors } from "../../charts/theme";
import { waterfallBars } from "../../charts/waterfall";
import { Card, ChartCard, Segmented } from "../../components/Card";
import { DataTable } from "../../components/DataTable";
import { useMetricDebugger } from "../../components/MetricDebugger";
import { PageHeader, SectionTitle } from "../../components/PageHeader";
import { PageSkeleton, Skeleton } from "../../components/Skeleton";
import { Callout, EmptyState, ErrorState } from "../../components/States";
import { DatasetTabs, FailedView, ProcessingView } from "../../features/datasets/DatasetChrome";
import { FiltersBar } from "../../features/datasets/FiltersBar";
import { EMPTY_FILTERS, filtersToQuery, useDatasetDashboard, useDatasetPerformance, useDatasetStatus } from "../../features/datasets/queries";
import { formatMetricValue, formatNumber, formatPercent, formatShare } from "../../lib/format";

const DIMENSIONS: { value: PerformanceDimension; label: string }[] = [
  { value: "categories", label: "Category" },
  { value: "products", label: "Product" },
  { value: "channels", label: "Channel" },
  { value: "regions", label: "Region" },
];

function useDimension<T>(groups: Partial<Record<PerformanceDimension, T>>, label: string) {
  const [selected, setSelected] = useState<PerformanceDimension>("categories");
  const options = DIMENSIONS.filter((option) => groups[option.value] !== undefined);
  const dimension = groups[selected] !== undefined ? selected : options[0]?.value;
  return {
    group: dimension ? groups[dimension] : undefined,
    control: dimension ? <Segmented value={dimension} options={options} onChange={setSelected} label={label} /> : null,
  };
}

function Figure({ label, value, context }: { label: string; value: string; context?: string }) {
  return (
    <Card>
      <span className="kpi-label">{label}</span>
      <div className="kpi-value tabular">{value}</div>
      {context && <span className="kpi-context">{context}</span>}
    </Card>
  );
}

function UnavailableSection({ section }: { section: Unavailable }) {
  return (
    <Callout tone="info" title="Not available for this file">
      {section.reason}
    </Callout>
  );
}

interface BarRow {
  label: string;
  value: number | null;
  detail?: string;
  small_sample?: boolean;
}

function GroupBars({ rows, label, currency, rate = false }: { rows: BarRow[]; label: string; currency?: string | null; rate?: boolean }) {
  const plotted = useMemo(() => {
    const valued = rows.filter((row) => row.value !== null);
    return rate ? [...valued].sort((left, right) => (left.value as number) - (right.value as number)) : [...valued].reverse();
  }, [rows, rate]);
  const data = useMemo(
    () => [
      {
        type: "bar",
        orientation: "h",
        y: plotted.map((row) => row.label),
        x: plotted.map((row) => (rate ? (row.value as number) * 100 : row.value)),
        marker: { color: plotted.map((row) => (row.small_sample ? chartColors.partial : (row.value as number) < 0 ? chartColors.breach : chartColors.accent)) },
        customdata: plotted.map((row) => [rate ? formatPercent(row.value) : formatMetricValue(row.value, "currency", currency), row.detail ?? ""]),
        hovertemplate: `<b>%{y}</b><br>${label}: %{customdata[0]}<br>%{customdata[1]}<extra></extra>`,
      },
    ],
    [plotted, rate, currency, label],
  );
  const layout = useMemo(
    () => ({
      margin: { l: 8, r: 16, t: 8, b: 44 },
      xaxis: { title: { text: label }, ticksuffix: rate ? "%" : "", tickformat: rate ? ".1f" : ",.3s", showgrid: true, zeroline: true },
      yaxis: { automargin: true },
      bargap: 0.3,
      showlegend: false,
    }),
    [rate, label],
  );
  if (plotted.length === 0) return <EmptyState title="No groups to chart" text="No calculated values are available for this selection." />;
  return <Plot data={data} layout={layout} height={Math.max(260, plotted.length * 28 + 80)} ariaLabel={`${label} by group`} />;
}

function BridgeChart({ bridge }: { bridge: RevenueBridge }) {
  const data = useMemo(() => {
    const bars = waterfallBars(bridge.steps);
    return [
      {
        type: "bar",
        x: bars.map((bar) => bar.label),
        y: bars.map((bar) => bar.height),
        base: bars.map((bar) => bar.base),
        marker: { color: bars.map((bar) => (bar.kind === "total" ? chartColors.accent : chartColors.breach)) },
        text: bars.map((bar) => formatMetricValue(bar.value, "currency", bridge.currency)),
        textposition: "outside",
        cliponaxis: false,
        hovertemplate: "<b>%{x}</b><br>%{text}<extra></extra>",
      },
    ];
  }, [bridge]);
  const layout = useMemo(
    () => ({
      margin: { l: 60, r: 24, t: 44, b: 64 },
      showlegend: false,
      yaxis: { tickformat: ",.3s", title: { text: bridge.currency ?? "Value" }, rangemode: "tozero" },
      xaxis: { type: "category" },
      bargap: 0.35,
    }),
    [bridge.currency],
  );
  return <Plot data={data} layout={layout} height={340} ariaLabel="Revenue bridge from gross sales to net revenue and profit" />;
}

function BridgeSection({ bridge, datasetId, query }: { bridge: RevenueBridge; datasetId: string; query: string }) {
  const { open } = useMetricDebugger();
  return (
    <div className="stack">
      <ChartCard
        title="From gross sales to gross profit"
        chart={<BridgeChart bridge={bridge} />}
        footer={bridge.identity}
        table={
          <DataTable
            rows={bridge.steps}
            rowKey={(row, index) => `${index}-${row.label}`}
            columns={[
              { key: "label", header: "Step" },
              { key: "value", header: "Value", align: "right", render: (row) => formatMetricValue(row.value, "currency", bridge.currency) },
              {
                key: "calculation",
                header: "Calculation",
                render: (row) =>
                  row.metric_id ? (
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      onClick={() => open({ source: "dataset", datasetId, metricId: row.metric_id!, query })}
                    >
                      How is this calculated?
                    </button>
                  ) : null,
              },
            ]}
          />
        }
      />
      {bridge.notes.map((note, index) => (
        <p key={index} className="text-xs muted">
          {note}
        </p>
      ))}
      {!bridge.reconciles && (
        <Callout tone="warning" title="Revenue bridge does not reconcile">
          The bridge totals do not reconcile to net revenue. Review the contributing rows and calculation notes.
        </Callout>
      )}
    </div>
  );
}

function ProfitabilitySection({ section }: { section: Profitability }) {
  const { group, control } = useDimension(section.groups, "Profitability dimension");
  const coverage = section.cost_coverage;
  return (
    <div className="stack" style={{ gap: 16 }}>
      <div className="grid grid-kpi">
        <Figure label="Gross profit" value={formatMetricValue(section.gross_profit, "currency", section.currency)} />
        <Figure label="Margin" value={formatPercent(section.margin)} />
        <Figure
          label="Cost coverage"
          value={formatShare(coverage.contributing_rows > 0 ? coverage.rows_with_cost / coverage.contributing_rows : null)}
          context={`${formatNumber(coverage.rows_with_cost)} of ${formatNumber(coverage.contributing_rows)} contributing rows`}
        />
      </div>
      <ChartCard
        title="Gross profit by group"
        extraActions={control}
        footer={section.note}
        chart={
          <GroupBars
            rows={(group?.rows ?? []).map((row) => ({ label: row.label, value: row.gross_profit, detail: `Margin: ${formatPercent(row.margin)}` }))}
            label="Gross profit"
            currency={section.currency}
          />
        }
        table={
          <DataTable
            rows={group?.rows ?? []}
            rowKey={(row) => row.label}
            columns={[
              { key: "label", header: "Group", sortValue: (row) => row.label },
              {
                key: "revenue",
                header: "Revenue",
                align: "right",
                sortValue: (row) => row.revenue,
                render: (row) => formatMetricValue(row.revenue, "currency", section.currency),
              },
              {
                key: "cost",
                header: "Cost",
                align: "right",
                sortValue: (row) => row.cost,
                render: (row) => formatMetricValue(row.cost, "currency", section.currency),
              },
              {
                key: "gross_profit",
                header: "Gross profit",
                align: "right",
                sortValue: (row) => row.gross_profit,
                render: (row) => formatMetricValue(row.gross_profit, "currency", section.currency),
              },
              { key: "margin", header: "Margin", align: "right", sortValue: (row) => row.margin, render: (row) => formatPercent(row.margin) },
            ]}
          />
        }
      />
      {group && group.total_groups > 4 && (
        <Card title="Lowest-margin groups">
          <ul className="list">
            {group.lowest_margin.map((row) => (
              <li key={row.label}>
                <strong>{row.label}</strong>: {formatPercent(row.margin)} margin · {formatMetricValue(row.gross_profit, "currency", section.currency)} gross
                profit
              </li>
            ))}
          </ul>
        </Card>
      )}
      {group && group.loss_making_groups > 0 && (
        <Callout tone="info" title="Loss-making groups">
          {formatNumber(group.loss_making_groups)} groups have negative gross profit in this dimension.
        </Callout>
      )}
    </div>
  );
}

function ReturnsSection({ section }: { section: ReturnsAnalysis }) {
  const { group, control } = useDimension(section.groups, "Returns dimension");
  return (
    <div className="stack" style={{ gap: 16 }}>
      <div className="grid grid-kpi">
        <Figure label="Return rate" value={formatPercent(section.return_rate)} />
        <Figure label="Returns value" value={formatMetricValue(section.returns_value, "currency", section.currency)} />
        <Figure label="Return rows" value={formatNumber(section.return_rows)} />
      </div>
      <ChartCard
        title="Return rate by group"
        extraActions={control}
        footer={section.note}
        chart={
          <div className="stack">
            <GroupBars
              rows={(group?.rows ?? []).map((row) => ({ label: row.label, value: row.return_rate, small_sample: row.small_sample }))}
              label="Return rate"
              rate
            />
            <p className="text-xs muted">Grey = fewer than 30 sale rows</p>
          </div>
        }
        table={
          <DataTable
            rows={group?.rows ?? []}
            rowKey={(row) => row.label}
            columns={[
              { key: "label", header: "Group", sortValue: (row) => row.label },
              {
                key: "gross_sales",
                header: "Gross sales",
                align: "right",
                sortValue: (row) => row.gross_sales,
                render: (row) => formatMetricValue(row.gross_sales, "currency", section.currency),
              },
              {
                key: "net_sales",
                header: "After discounts",
                align: "right",
                sortValue: (row) => row.net_sales,
                render: (row) => formatMetricValue(row.net_sales, "currency", section.currency),
              },
              {
                key: "returns_value",
                header: "Returns",
                align: "right",
                sortValue: (row) => row.returns_value,
                render: (row) => formatMetricValue(row.returns_value, "currency", section.currency),
              },
              { key: "return_rate", header: "Rate", align: "right", sortValue: (row) => row.return_rate, render: (row) => formatPercent(row.return_rate) },
              { key: "sale_rows", header: "Sale rows", align: "right", sortValue: (row) => row.sale_rows, render: (row) => formatNumber(row.sale_rows) },
              {
                key: "return_rows",
                header: "Return rows",
                align: "right",
                sortValue: (row) => row.return_rows,
                render: (row) => formatNumber(row.return_rows),
              },
            ]}
          />
        }
      />
    </div>
  );
}

function DiscountTrend({ trend }: { trend: DiscountsAnalysis["trend"] }) {
  const data = useMemo(
    () => [
      {
        type: "scatter",
        mode: "lines+markers",
        x: (trend.points ?? []).map((point) => point.period),
        y: (trend.points ?? []).map((point) => (point.discount_rate === null ? null : point.discount_rate * 100)),
        line: { color: chartColors.accent },
        connectgaps: false,
        hovertemplate: "%{x}<br>Discount rate: %{y:.1f}%<extra></extra>",
      },
    ],
    [trend.points],
  );
  const layout = useMemo(
    () => ({
      margin: { l: 48, r: 8, t: 8, b: 40 },
      yaxis: { ticksuffix: "%", title: { text: "Discount rate" } },
      xaxis: { type: "date", tickformat: "%b %Y" },
    }),
    [],
  );
  return <Plot data={data} layout={layout} height={280} ariaLabel="Monthly discount rate" />;
}

function DiscountsSection({ section }: { section: DiscountsAnalysis }) {
  const { group, control } = useDimension(section.groups, "Discounts dimension");
  const split = section.margin_split;
  return (
    <div className="stack" style={{ gap: 16 }}>
      <div className="grid grid-kpi">
        <Figure label="Discount rate" value={formatPercent(section.discount_rate)} />
        <Figure label="Discounts value" value={formatMetricValue(section.discount_value, "currency", section.currency)} />
        <Figure
          label="Sale rows discounted"
          value={formatShare(section.discounted_row_share)}
          context={`${formatNumber(section.discounted_rows)} of ${formatNumber(section.sale_rows)} sale rows`}
        />
      </div>
      <p className="text-xs muted">
        {section.treatment === "deducted"
          ? "Discounts were subtracted from gross sales."
          : "Amounts already had discounts deducted, so discounts are reported, not subtracted again."}
      </p>
      <ChartCard
        title="Discount rate by group"
        extraActions={control}
        footer={section.note}
        chart={<GroupBars rows={(group?.rows ?? []).map((row) => ({ label: row.label, value: row.discount_rate }))} label="Discount rate" rate />}
        table={
          <DataTable
            rows={group?.rows ?? []}
            rowKey={(row) => row.label}
            columns={[
              { key: "label", header: "Group", sortValue: (row) => row.label },
              {
                key: "discount_rate",
                header: "Discount rate",
                align: "right",
                sortValue: (row) => row.discount_rate,
                render: (row) => formatPercent(row.discount_rate),
              },
              {
                key: "discount_value",
                header: "Discounts",
                align: "right",
                sortValue: (row) => row.discount_value,
                render: (row) => formatMetricValue(row.discount_value, "currency", section.currency),
              },
              {
                key: "list_value",
                header: "List value",
                align: "right",
                sortValue: (row) => row.list_value,
                render: (row) => formatMetricValue(row.list_value, "currency", section.currency),
              },
              {
                key: "discounted_row_share",
                header: "Rows discounted",
                align: "right",
                sortValue: (row) => row.discounted_row_share,
                render: (row) => formatShare(row.discounted_row_share),
              },
            ]}
          />
        }
      />
      {section.trend.available ? (
        <ChartCard
          title="Monthly discount rate"
          chart={<DiscountTrend trend={section.trend} />}
          footer={section.trend.note}
          table={
            <DataTable
              rows={section.trend.points ?? []}
              rowKey={(row) => row.period}
              columns={[
                { key: "period", header: "Month", sortValue: (row) => row.period },
                { key: "discount_rate", header: "Discount rate", align: "right", render: (row) => formatPercent(row.discount_rate) },
                {
                  key: "discount_value",
                  header: "Discounts",
                  align: "right",
                  render: (row) => formatMetricValue(row.discount_value, "currency", section.currency),
                },
              ]}
            />
          }
        />
      ) : (
        <Callout tone="info" title="Discount trend unavailable">
          {section.trend.reason}
        </Callout>
      )}
      {split && (
        <Card
          title="Margin on discounted vs full-price rows"
          footer="Descriptive comparison only; discounted items may differ in mix, so this is not the causal effect of discounting."
        >
          <div className="grid grid-2">
            {[
              { label: "Discounted rows", side: split.discounted },
              { label: "Full-price rows", side: split.full_price },
            ].map(({ label, side }) => (
              <div key={label}>
                <span className="kpi-label">{label}</span>
                <div className="kpi-value tabular">{formatPercent(side.margin)}</div>
                <span className="kpi-context">
                  {formatMetricValue(side.revenue, "currency", section.currency)} revenue · {formatNumber(side.rows)} rows
                </span>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}

function ParetoChart({ summary, label }: { summary: ParetoSummary; label: string }) {
  const data = useMemo(
    () => [
      {
        type: "scatter",
        mode: "lines",
        x: [0, 100],
        y: [0, 100],
        line: { color: chartColors.ink3, width: 1, dash: "dot" },
        name: "Perfect equality",
        hoverinfo: "skip",
      },
      {
        type: "scatter",
        mode: "lines",
        x: summary.curve.map((point) => point.item_share * 100),
        y: summary.curve.map((point) => point.revenue_share * 100),
        line: { color: chartColors.accent, width: 2.6 },
        name: label,
        hovertemplate: "%{x:.1f}% of items<br>%{y:.1f}% of revenue<extra></extra>",
      },
    ],
    [summary.curve, label],
  );
  const layout = useMemo(
    () => ({
      margin: { l: 56, r: 8, t: 36, b: 48 },
      showlegend: true,
      legend: { orientation: "h", x: 0, y: 1, yanchor: "bottom" },
      xaxis: { range: [0, 100], ticksuffix: "%", title: { text: "Share of items" } },
      yaxis: { range: [0, 100], ticksuffix: "%", title: { text: "Cumulative share of revenue" } },
    }),
    [],
  );
  return <Plot data={data} layout={layout} height={320} ariaLabel={`${label} revenue Pareto curve`} />;
}

function ConcentrationCard({
  summary,
  label,
  currency,
  note,
  products = false,
}: {
  summary: ParetoSummary | Unavailable;
  label: string;
  currency: string | null;
  note: string;
  products?: boolean;
}) {
  if (!summary.available) return <UnavailableSection section={summary} />;
  const stats = (
    <dl className="kv">
      <dt>Top 20% share</dt>
      <dd>{formatShare(summary.top_20pct_share)}</dd>
      <dt>Items for 80% of revenue</dt>
      <dd>{formatNumber(summary.items_for_80pct)}</dd>
      <dt>Gini</dt>
      <dd>{formatMetricValue(summary.gini, "index")}</dd>
      <dt>Items</dt>
      <dd>{formatNumber(summary.items)}</dd>
      <dt>Excluded non-positive items</dt>
      <dd>{formatNumber(summary.excluded_non_positive)}</dd>
    </dl>
  );
  const topItems = products && summary.top_items && (
    <div className="stack">
      <h4>Top products</h4>
      <ul className="list">
        {summary.top_items.map((item) => (
          <li key={item.label}>
            <strong>{item.label}</strong>: {formatMetricValue(item.revenue, "currency", currency)} · {formatShare(item.share)}
          </li>
        ))}
      </ul>
    </div>
  );
  return (
    <ChartCard
      title={label}
      footer={note}
      chart={
        <div className="stack">
          <ParetoChart summary={summary} label={label} />
          {stats}
          {topItems}
        </div>
      }
      table={
        <div className="stack">
          {stats}
          <DataTable
            rows={summary.curve}
            rowKey={(_, index) => String(index)}
            columns={[
              { key: "item_share", header: "Share of items", align: "right", render: (row) => formatShare(row.item_share) },
              { key: "revenue_share", header: "Cumulative revenue", align: "right", render: (row) => formatShare(row.revenue_share) },
            ]}
            maxHeight={320}
          />
          {topItems}
        </div>
      }
    />
  );
}

function ConcentrationSection({ section }: { section: Concentration }) {
  return (
    <div className="grid grid-2">
      <ConcentrationCard summary={section.products} label="Products" currency={section.currency} note={section.note} products />
      <ConcentrationCard summary={section.customers} label="Customers" currency={section.currency} note={section.note} />
    </div>
  );
}

function PerformanceContent({ data, datasetId, query }: { data: DatasetPerformance; datasetId: string; query: string }) {
  return (
    <>
      <SectionTitle
        title="Revenue bridge"
        description="Every step comes from the same contributing rows; click a step in the table view to open its calculation."
      />
      {data.bridge.available ? <BridgeSection bridge={data.bridge} datasetId={datasetId} query={query} /> : <UnavailableSection section={data.bridge} />}
      <SectionTitle title="Profitability" description="Recorded cost only; profit is never estimated." />
      {data.profitability.available ? <ProfitabilitySection section={data.profitability} /> : <UnavailableSection section={data.profitability} />}
      <SectionTitle title="Returns" description="Returned value relative to the sales it reverses." />
      {data.returns.available ? <ReturnsSection section={data.returns} /> : <UnavailableSection section={data.returns} />}
      <SectionTitle title="Discounts" description="How much list value is given away, and where." />
      {data.discounts.available ? <DiscountsSection section={data.discounts} /> : <UnavailableSection section={data.discounts} />}
      <SectionTitle title="Concentration" description="How dependent revenue is on a few products and customers." />
      {data.concentration.available ? <ConcentrationSection section={data.concentration} /> : <UnavailableSection section={data.concentration} />}
    </>
  );
}

export function DatasetPerformancePage() {
  const { datasetId = "" } = useParams();
  const [filters, setFilters] = useState<DatasetFilters>(EMPTY_FILTERS);
  const status = useDatasetStatus(datasetId);
  const ready = status.data?.dataset.status === "ready";
  const version = status.data?.dataset.data_version;
  const dashboard = useDatasetDashboard(datasetId, version, EMPTY_FILTERS, ready);
  const performance = useDatasetPerformance(datasetId, version, filters, ready);
  if (status.isPending) return <PageSkeleton />;
  if (status.isError) return <EmptyState title="Dataset not found" text="It may have expired, been deleted, or belong to another browser session." />;
  if (status.data.dataset.status === "failed") return <FailedView status={status.data} />;
  if (!ready) return <ProcessingView status={status.data} />;
  return (
    <div className="page">
      <PageHeader
        eyebrow="Your data · performance"
        title={status.data.dataset.display_name}
        description="Where revenue is gained and lost: discounts, returns, cost and concentration, on the same contributing rows as the dashboard."
        actions={<DatasetTabs datasetId={datasetId} active="performance" />}
      />
      {dashboard.isPending ? (
        <Skeleton height={80} />
      ) : dashboard.isError ? (
        <ErrorState title="Could not load filter options" text={dashboard.error.message} />
      ) : (
        <FiltersBar dashboard={dashboard.data} filters={filters} onChange={setFilters} />
      )}
      {performance.isPending ? (
        <PageSkeleton />
      ) : performance.isError ? (
        <ErrorState title="Could not load performance" text={performance.error.message} />
      ) : (
        <PerformanceContent data={performance.data} datasetId={datasetId} query={filtersToQuery(filters)} />
      )}
    </div>
  );
}
