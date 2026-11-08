import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import type { Breakdown, DatasetDashboard, DatasetFilters, DatasetStatusPayload, Trend } from "../../api/datasetTypes";
import { Plot } from "../../charts/Plot";
import { chartColors } from "../../charts/theme";
import { Card, ChartCard } from "../../components/Card";
import { DataTable } from "../../components/DataTable";
import { ForecastCard } from "../../components/ForecastCard";
import { KpiCard } from "../../components/KpiCard";
import { PageHeader, SectionTitle } from "../../components/PageHeader";
import { PageSkeleton } from "../../components/Skeleton";
import { Callout, EmptyState, ErrorState } from "../../components/States";
import { IconClose } from "../../components/icons";
import { ClarificationsBanner, DatasetTabs, ExportMenu, FailedView, ProcessingView, SchemaBadges } from "../../features/datasets/DatasetChrome";
import { FiltersBar } from "../../features/datasets/FiltersBar";
import { EMPTY_FILTERS, filtersToQuery, useDatasetDashboard, useDatasetStatus, useDeleteDataset, useUpdateMapping } from "../../features/datasets/queries";
import { currencySymbol, formatMetricValue, formatNumber, formatPercent } from "../../lib/format";
import { useFocusTrap } from "../../lib/useFocusTrap";

const BREAKDOWN_TITLES: Record<string, string> = {
  products: "Top products",
  categories: "Categories",
  regions: "Regions",
  channels: "Sales channels",
};

function TrendChart({ trend, currency, metric, ordersLabel }: { trend: Trend; currency: string | null; metric: "revenue" | "orders"; ordersLabel: string }) {
  const points = useMemo(() => trend.points ?? [], [trend.points]);
  const data = useMemo(() => {
    const values = points.map((point) => (metric === "revenue" ? point.revenue : point.orders));
    const symbol = currencySymbol(currency);
    return [
      {
        type: "bar",
        x: points.map((point) => point.period),
        y: values,
        marker: { color: points.map((point) => (point.is_partial ? chartColors.partial : chartColors.accent)) },
        customdata: points.map((point) => [point.period_end, point.is_partial ? "<br><i>Partial period</i>" : "", point.orders]),
        hovertemplate:
          metric === "revenue"
            ? `<b>%{x|%Y-%m-%d}</b> → %{customdata[0]}<br>${symbol ? `${symbol} ` : ""}%{y:,.0f}<br>%{customdata[2]:,} ${ordersLabel.toLowerCase()}%{customdata[1]}<extra></extra>`
            : `<b>%{x|%Y-%m-%d}</b> → %{customdata[0]}<br>%{y:,} ${ordersLabel.toLowerCase()}%{customdata[1]}<extra></extra>`,
      },
    ];
  }, [points, metric, currency, ordersLabel]);
  const layout = useMemo(
    () => ({
      margin: { l: 60, r: 8, t: 8, b: 40 },
      yaxis: {
        tickformat: metric === "revenue" ? ",.3s" : ",.0f",
        title: { text: metric === "revenue" ? `Net revenue${currency ? ` (${currency})` : ""}` : ordersLabel },
      },
      xaxis: { type: "date", tickformat: trend.granularity === "month" ? "%b %Y" : "%d %b" },
      bargap: 0.25,
    }),
    [metric, currency, trend.granularity, ordersLabel],
  );
  return <Plot data={data} layout={layout} height={300} ariaLabel={`${metric} over time`} />;
}

function BreakdownChart({ breakdown, currency }: { breakdown: Breakdown; currency: string | null }) {
  const rows = useMemo(() => [...(breakdown.rows ?? [])].slice(0, 10).reverse(), [breakdown.rows]);
  const showRevenue = Boolean(breakdown.revenue_shown);
  const data = useMemo(
    () => [
      {
        type: "bar",
        orientation: "h",
        y: rows.map((row) => row.label),
        x: rows.map((row) => (showRevenue ? row.revenue : row.orders)),
        marker: { color: chartColors.accent },
        text: rows.map((row) => (showRevenue ? formatPercent(row.revenue_share) : formatNumber(row.orders))),
        textposition: "outside",
        cliponaxis: false,
        customdata: rows.map((row) => [row.orders, row.units ?? 0, row.rows]),
        hovertemplate: showRevenue
          ? `<b>%{y}</b><br>${currencySymbol(currency) ? currencySymbol(currency) + " " : ""}%{x:,.0f}<br>%{customdata[0]:,} orders · %{customdata[1]:,} units<extra></extra>`
          : "<b>%{y}</b><br>%{x:,} orders<extra></extra>",
      },
    ],
    [rows, showRevenue, currency],
  );
  const layout = useMemo(
    () => ({ margin: { l: 8, r: 48, t: 4, b: 32 }, xaxis: { tickformat: showRevenue ? ",.3s" : ",.0f", showgrid: true }, bargap: 0.3 }),
    [showRevenue],
  );
  return <Plot data={data} layout={layout} height={Math.max(220, rows.length * 30 + 60)} ariaLabel="Breakdown chart" />;
}

function BreakdownCard({ name, breakdown, currency, stagger }: { name: string; breakdown: Breakdown; currency: string | null; stagger: number }) {
  const showRevenue = Boolean(breakdown.revenue_shown);
  return (
    <ChartCard
      title={BREAKDOWN_TITLES[name] ?? name}
      subtitle={`${breakdown.column ? `From '${breakdown.column}' · ` : ""}${formatNumber(breakdown.total_groups ?? 0)} groups${showRevenue ? " · share of net revenue" : ""}`}
      chart={<BreakdownChart breakdown={breakdown} currency={currency} />}
      table={
        <DataTable
          rows={breakdown.rows ?? []}
          rowKey={(row) => row.label}
          maxHeight={360}
          columns={[
            { key: "label", header: "Group", sortValue: (row) => row.label },
            ...(showRevenue
              ? [
                  {
                    key: "revenue",
                    header: "Net revenue",
                    align: "right" as const,
                    sortValue: (row: { revenue: number | null }) => row.revenue,
                    render: (row: { revenue: number | null }) => formatMetricValue(row.revenue, "currency", currency),
                  },
                  {
                    key: "share",
                    header: "Share",
                    align: "right" as const,
                    render: (row: { revenue_share: number | null }) => formatPercent(row.revenue_share),
                  },
                ]
              : []),
            { key: "orders", header: "Orders", align: "right", sortValue: (row) => row.orders, render: (row) => formatNumber(row.orders) },
            { key: "units", header: "Units", align: "right", sortValue: (row) => row.units, render: (row) => formatNumber(row.units) },
          ]}
        />
      }
      footer={
        <>
          {breakdown.others ? `${breakdown.others.label}${showRevenue ? ` = ${formatPercent(breakdown.others.revenue_share)} of revenue` : ""}. ` : ""}
          {breakdown.note}
        </>
      }
      stagger={stagger}
    />
  );
}

function MappingDrawer({ status, onClose }: { status: DatasetStatusPayload; onClose: () => void }) {
  const schema = status.schema;
  const mutation = useUpdateMapping(status.dataset.dataset_id);
  const closeRef = useRef<HTMLButtonElement | null>(null);
  const drawerRef = useRef<HTMLDivElement | null>(null);
  useFocusTrap(drawerRef);
  const initial = useMemo(() => {
    const mapping: Record<string, string> = {};
    for (const [role, entry] of Object.entries(schema?.assignments ?? {})) mapping[role] = entry.column_name;
    return mapping;
  }, [schema]);
  const [mapping, setMapping] = useState<Record<string, string>>(initial);
  useEffect(() => {
    closeRef.current?.focus();
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  if (!schema) return null;
  const changed = schema.role_options.filter((option) => (mapping[option.role] ?? "") !== (initial[option.role] ?? ""));
  return (
    <>
      <div className="drawer-overlay" onClick={onClose} aria-hidden="true" />
      <div ref={drawerRef} className="drawer" role="dialog" aria-modal="true" aria-labelledby="mapping-title">
        <header className="drawer-header">
          <div className="stack" style={{ gap: 6 }}>
            <span className="badge badge-accent" style={{ alignSelf: "flex-start" }}>
              Optional
            </span>
            <h2 id="mapping-title" style={{ fontSize: "1.25rem" }}>
              Advanced column mapping
            </h2>
            <span className="text-sm muted">MIERU mapped these automatically. Change a role only if it is wrong; the file is re-analysed in seconds.</span>
          </div>
          <button ref={closeRef} type="button" className="icon-btn" onClick={onClose} aria-label="Close mapping panel">
            <IconClose />
          </button>
        </header>
        <div className="drawer-body">
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Role</th>
                  <th>Column</th>
                </tr>
              </thead>
              <tbody>
                {schema.role_options.map((option) => (
                  <tr key={option.role}>
                    <td>
                      {option.label}
                      {initial[option.role] && <div className="text-xs muted">detected: {initial[option.role]}</div>}
                    </td>
                    <td>
                      <select
                        className="select"
                        aria-label={`Column for ${option.label}`}
                        value={mapping[option.role] ?? ""}
                        onChange={(event) => setMapping((current) => ({ ...current, [option.role]: event.target.value }))}
                      >
                        <option value="">— not mapped —</option>
                        {schema.columns.map((column) => (
                          <option key={column} value={column}>
                            {column}
                          </option>
                        ))}
                      </select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {mutation.isError && <Callout tone="critical">{(mutation.error as Error).message}</Callout>}
          <div className="row" style={{ justifyContent: "flex-end" }}>
            <button type="button" className="btn btn-ghost" onClick={onClose}>
              Cancel
            </button>
            <button
              type="button"
              className="btn btn-primary"
              disabled={changed.length === 0 || mutation.isPending}
              onClick={() => {
                const payload: Record<string, string | null> = {};
                for (const option of changed) payload[option.role] = mapping[option.role] || null;
                mutation.mutate(payload, { onSuccess: onClose });
              }}
            >
              {mutation.isPending ? "Applying…" : `Apply ${changed.length || ""} change${changed.length === 1 ? "" : "s"} & re-analyse`}
            </button>
          </div>
        </div>
      </div>
    </>
  );
}

function DashboardContent({
  status,
  dashboard,
  filters,
  setFilters,
}: {
  status: DatasetStatusPayload;
  dashboard: DatasetDashboard;
  filters: DatasetFilters;
  setFilters: (filters: DatasetFilters) => void;
}) {
  const navigate = useNavigate();
  const [mappingOpen, setMappingOpen] = useState(false);
  const [trendMetric, setTrendMetric] = useState<"revenue" | "orders">("revenue");
  const deletion = useDeleteDataset(status.dataset.dataset_id);
  const dataset = dashboard.dataset;
  const query = filtersToQuery(filters);
  const available = dashboard.kpis.filter((kpi) => kpi.status === "ok");
  const unavailableKpis = dashboard.kpis.filter((kpi) => kpi.status !== "ok");
  const unavailableBreakdowns = Object.entries(dashboard.breakdowns).filter(([, breakdown]) => !breakdown.available);
  const comparison = dashboard.trend.comparison;
  const revenueAvailable = Boolean(dashboard.trend.revenue_available);
  return (
    <div className="page">
      <PageHeader
        eyebrow={`Your data · ${dataset.format.toUpperCase()}`}
        title={dataset.display_name}
        description={dataset.grain_explanation}
        actions={
          <>
            <DatasetTabs datasetId={dataset.dataset_id} active="dashboard" />
            <ExportMenu datasetId={dataset.dataset_id} query={query} />
            <button type="button" className="btn" onClick={() => setMappingOpen(true)}>
              Advanced mapping
            </button>
            <button
              type="button"
              className="btn btn-ghost"
              disabled={deletion.isPending}
              onClick={() => {
                if (window.confirm("Delete this uploaded dataset from MIERU? Your original file on your computer is not affected.")) {
                  deletion.mutate(undefined, { onSuccess: () => navigate("/data") });
                }
              }}
            >
              Delete
            </button>
          </>
        }
      />
      <div className="row row-wrap">
        <SchemaBadges grain={dataset.grain} basis={dataset.revenue_basis} currency={dataset.currency} rows={dataset.rows} />
      </div>
      <ClarificationsBanner assumptions={dashboard.assumptions} clarifications={dashboard.clarifications} />
      <FiltersBar dashboard={dashboard} filters={filters} onChange={setFilters} />

      <div className="grid grid-kpi">
        {available.map((kpi, index) => (
          <KpiCard
            key={kpi.metric_id}
            label={kpi.label}
            value={kpi.value}
            unit={kpi.unit}
            currency={kpi.currency}
            metric={{ source: "dataset", datasetId: dataset.dataset_id, metricId: kpi.metric_id, query }}
            stagger={index}
          />
        ))}
      </div>

      {dashboard.trend.available ? (
        <ChartCard
          title="Performance over time"
          subtitle={`${dashboard.trend.granularity === "month" ? "Monthly" : dashboard.trend.granularity === "week" ? "Weekly" : "Daily"} · ${dashboard.trend.first_date} → ${dashboard.trend.last_date} · grey = partial period`}
          extraActions={
            <>
              {comparison?.available && (
                <span className={`badge ${(comparison.revenue_change ?? 0) >= 0 ? "badge-good" : "badge-breach"}`} title={comparison.note}>
                  {revenueAvailable ? "Revenue" : dataset.orders_label}{" "}
                  {formatPercent(revenueAvailable ? (comparison.revenue_change ?? null) : (comparison.orders_change ?? null))} vs previous period
                </span>
              )}
              {revenueAvailable && (
                <div className="segmented" role="group" aria-label="Trend metric">
                  <button type="button" aria-pressed={trendMetric === "revenue"} onClick={() => setTrendMetric("revenue")}>
                    Revenue
                  </button>
                  <button type="button" aria-pressed={trendMetric === "orders"} onClick={() => setTrendMetric("orders")}>
                    {dataset.orders_label}
                  </button>
                </div>
              )}
            </>
          }
          chart={
            <TrendChart
              trend={dashboard.trend}
              currency={dataset.currency}
              metric={revenueAvailable ? trendMetric : "orders"}
              ordersLabel={dataset.orders_label}
            />
          }
          table={
            <DataTable
              rows={dashboard.trend.points ?? []}
              rowKey={(row) => row.period}
              maxHeight={300}
              columns={[
                { key: "period", header: "Period", sortValue: (row) => row.period, render: (row) => `${row.period}${row.is_partial ? " (partial)" : ""}` },
                {
                  key: "revenue",
                  header: "Net revenue",
                  align: "right",
                  sortValue: (row) => row.revenue,
                  render: (row) => formatMetricValue(row.revenue, "currency", dataset.currency),
                },
                { key: "orders", header: dataset.orders_label, align: "right", sortValue: (row) => row.orders, render: (row) => formatNumber(row.orders) },
              ]}
            />
          }
        />
      ) : (
        <Callout tone="info" title="Trends are not available for this file">
          {dashboard.trend.reason}
        </Callout>
      )}

      <ForecastCard endpoint={`/api/datasets/${dataset.dataset_id}/forecast?v=${dataset.data_version}`} title="Forecast" />

      <SectionTitle title="Breakdowns" description="Totals reconcile to the KPIs above (same rows, same exclusions)." />
      <div className="grid grid-2">
        {Object.entries(dashboard.breakdowns)
          .filter(([, breakdown]) => breakdown.available)
          .map(([name, breakdown], index) => (
            <BreakdownCard key={name} name={name} breakdown={breakdown} currency={dataset.currency} stagger={index} />
          ))}
      </div>

      {(unavailableKpis.length > 0 || unavailableBreakdowns.length > 0) && (
        <Card title="Not available for this file" subtitle="MIERU never estimates values it cannot calculate from your data" stagger={2}>
          <ul className="list">
            {unavailableKpis.map((kpi) => (
              <li key={kpi.metric_id}>
                <strong>{kpi.label}:</strong> {kpi.unavailable_reason}
              </li>
            ))}
            {unavailableBreakdowns.map(([name, breakdown]) => (
              <li key={name}>
                <strong>{BREAKDOWN_TITLES[name]}:</strong> {breakdown.reason}
              </li>
            ))}
          </ul>
        </Card>
      )}
      {mappingOpen && <MappingDrawer status={status} onClose={() => setMappingOpen(false)} />}
    </div>
  );
}

export function DatasetDashboardPage() {
  const { datasetId = "" } = useParams();
  const [filters, setFilters] = useState<DatasetFilters>(EMPTY_FILTERS);
  const status = useDatasetStatus(datasetId);
  const ready = status.data?.dataset.status === "ready";
  const dashboard = useDatasetDashboard(datasetId, status.data?.dataset.data_version, filters, ready);

  if (status.isPending) return <PageSkeleton />;
  if (status.isError) {
    return <EmptyState title="Dataset not found" text="It may have expired, been deleted, or belong to another browser session." />;
  }
  if (status.data.dataset.status === "failed") return <FailedView status={status.data} />;
  if (!ready) return <ProcessingView status={status.data} />;
  if (dashboard.isPending) return <PageSkeleton kpis={6} />;
  if (dashboard.isError) return <ErrorState title="Could not build the dashboard" text={(dashboard.error as Error).message} />;
  return <DashboardContent status={status.data} dashboard={dashboard.data} filters={filters} setFilters={setFilters} />;
}
