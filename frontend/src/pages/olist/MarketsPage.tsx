import { useMemo } from "react";
import type { CategoryScore, MarketAssociation, MarketRateFields, OlistMarkets, StateScore } from "../../api/types";
import { Plot } from "../../charts/Plot";
import { chartColors } from "../../charts/theme";
import { Card, ChartCard } from "../../components/Card";
import { DataTable } from "../../components/DataTable";
import type { DataTableColumn } from "../../components/DataTable.types";
import { PageHeader, SectionTitle } from "../../components/PageHeader";
import { QueryBoundary } from "../../components/QueryBoundary";
import { Callout } from "../../components/States";
import { useOlistMarkets } from "../../features/olist/queries";
import { formatMetricValue, formatNumber, formatPercent, formatPValue, formatShare } from "../../lib/format";

function Rate({ value, ci }: { value: number | null; ci: [number | null, number | null] }) {
  return <span title={`Wilson 95% CI: ${formatPercent(ci[0])} to ${formatPercent(ci[1])}`}>{formatPercent(value)}</span>;
}

function qualityColumns<Row extends MarketRateFields>(): DataTableColumn<Row>[] {
  return [
    {
      key: "mean_review_score",
      header: "Mean review",
      align: "right",
      sortValue: (row) => row.mean_review_score,
      render: (row) => formatMetricValue(row.mean_review_score, "score"),
    },
    {
      key: "severe_detractor_rate",
      header: "Severe detractors",
      align: "right",
      sortValue: (row) => row.severe_detractor_rate,
      render: (row) => <Rate value={row.severe_detractor_rate} ci={row.severe_detractor_ci} />,
    },
    {
      key: "sla_breach_rate",
      header: "SLA breach",
      align: "right",
      sortValue: (row) => row.sla_breach_rate,
      render: (row) => <Rate value={row.sla_breach_rate} ci={row.sla_breach_ci} />,
    },
  ];
}

function CategoryTable({ rows }: { rows: CategoryScore[] }) {
  return (
    <DataTable
      rows={rows}
      rowKey={(row) => row.category}
      caption="Category scorecards, including small samples"
      maxHeight={560}
      columns={[
        {
          key: "display_name",
          header: "Category",
          sortValue: (row) => row.display_name,
          render: (row) => (
            <>
              <strong>{row.display_name}</strong>
              {!row.reliable && (
                <>
                  {" "}
                  <span className="badge muted">small sample</span>
                </>
              )}
            </>
          ),
        },
        { key: "gmv", header: "GMV", align: "right", sortValue: (row) => row.gmv, render: (row) => formatMetricValue(row.gmv, "currency", "BRL") },
        { key: "gmv_share", header: "GMV share", align: "right", sortValue: (row) => row.gmv_share, render: (row) => formatShare(row.gmv_share) },
        { key: "orders", header: "Orders", align: "right", sortValue: (row) => row.orders, render: (row) => formatNumber(row.orders) },
        ...qualityColumns<CategoryScore>(),
        {
          key: "freight_share",
          header: "Freight share",
          align: "right",
          sortValue: (row) => row.freight_share,
          render: (row) => formatShare(row.freight_share),
        },
        {
          key: "mean_delivery_days",
          header: "Mean delivery",
          align: "right",
          sortValue: (row) => row.mean_delivery_days,
          render: (row) => formatMetricValue(row.mean_delivery_days, "days"),
        },
      ]}
    />
  );
}

function StateTable({ rows }: { rows: StateScore[] }) {
  return (
    <DataTable
      rows={rows}
      rowKey={(row) => row.state}
      caption="Regional scorecards, including small samples"
      maxHeight={560}
      columns={[
        {
          key: "state_name",
          header: "State",
          sortValue: (row) => row.state_name,
          render: (row) => (
            <>
              <strong>
                {row.state_name} ({row.state})
              </strong>
              {!row.reliable && (
                <>
                  {" "}
                  <span className="badge muted">small sample</span>
                </>
              )}
            </>
          ),
        },
        { key: "gmv", header: "GMV", align: "right", sortValue: (row) => row.gmv, render: (row) => formatMetricValue(row.gmv, "currency", "BRL") },
        { key: "gmv_share", header: "GMV share", align: "right", sortValue: (row) => row.gmv_share, render: (row) => formatShare(row.gmv_share) },
        {
          key: "delivered_orders",
          header: "Orders",
          align: "right",
          sortValue: (row) => row.delivered_orders,
          render: (row) => formatNumber(row.delivered_orders),
        },
        {
          key: "average_order_value",
          header: "AOV",
          align: "right",
          sortValue: (row) => row.average_order_value,
          render: (row) => formatMetricValue(row.average_order_value, "currency", "BRL"),
        },
        ...qualityColumns<StateScore>(),
        {
          key: "median_delivery_days",
          header: "Median delivery",
          align: "right",
          sortValue: (row) => row.median_delivery_days,
          render: (row) => formatMetricValue(row.median_delivery_days, "days"),
        },
        {
          key: "median_promised_days",
          header: "Median promised",
          align: "right",
          sortValue: (row) => row.median_promised_days,
          render: (row) => formatMetricValue(row.median_promised_days, "days"),
        },
        {
          key: "median_distance_km",
          header: "Median distance",
          align: "right",
          sortValue: (row) => row.median_distance_km,
          render: (row) => <>{formatNumber(row.median_distance_km, 1)} km</>,
        },
      ]}
    />
  );
}

function AssociationCard({ association }: { association: MarketAssociation }) {
  if (!association.available)
    return (
      <Callout tone="info" title="Association unavailable">
        {association.reason}
      </Callout>
    );
  return (
    <Card title="Spearman association" subtitle={association.description} footer={association.caveat}>
      <span className="kpi-label">Spearman ρ</span>
      <div className="kpi-value tabular">{formatMetricValue(association.rho, "score")}</div>
      <span className="kpi-context">
        {formatPValue(association.p_value)} · {formatNumber(association.n_groups)} groups
      </span>
    </Card>
  );
}

function CategoryScatter({ rows }: { rows: CategoryScore[] }) {
  const reliable = useMemo(() => rows.filter((row) => row.reliable && row.sla_breach_rate !== null && row.mean_review_score !== null), [rows]);
  const data = useMemo(() => {
    const maxSize = Math.max(1, ...reliable.map((row) => Math.sqrt(Math.max(0, row.gmv))));
    return [
      {
        type: "scatter",
        mode: "markers",
        x: reliable.map((row) => (row.sla_breach_rate as number) * 100),
        y: reliable.map((row) => row.mean_review_score),
        marker: {
          color: chartColors.accent,
          opacity: 0.75,
          size: reliable.map((row) => (48 * Math.sqrt(Math.max(0, row.gmv))) / maxSize),
          sizemode: "diameter",
          line: { width: 1, color: chartColors.surface },
        },
        customdata: reliable.map((row) => [
          row.display_name,
          formatMetricValue(row.gmv, "currency", "BRL"),
          formatNumber(row.orders),
          formatPercent(row.severe_detractor_rate),
          formatPercent(row.sla_breach_rate),
          formatMetricValue(row.mean_review_score, "score"),
        ]),
        hovertemplate:
          "<b>%{customdata[0]}</b><br>GMV: %{customdata[1]}<br>Orders: %{customdata[2]}<br>Severe detractors: %{customdata[3]}<br>SLA breach: %{customdata[4]}<br>Mean review: %{customdata[5]}<extra></extra>",
      },
    ];
  }, [reliable]);
  const layout = useMemo(
    () => ({
      margin: { l: 52, r: 24, t: 24, b: 48 },
      xaxis: { title: { text: "SLA breach rate" }, ticksuffix: "%", rangemode: "tozero", showgrid: true },
      yaxis: { title: { text: "Mean review score" }, autorange: true, tickformat: ".1f" },
      hovermode: "closest",
      showlegend: false,
    }),
    [],
  );
  return <Plot data={data} layout={layout} height={380} ariaLabel="Reliable categories: SLA breach rate versus mean review score, sized by GMV" />;
}

function StateScatter({ rows }: { rows: StateScore[] }) {
  const reliable = useMemo(() => rows.filter((row) => row.reliable && row.median_delivery_days !== null && row.mean_review_score !== null), [rows]);
  const data = useMemo(() => {
    const maxSize = Math.max(1, ...reliable.map((row) => Math.sqrt(Math.max(0, row.gmv))));
    return [
      {
        type: "scatter",
        mode: "markers+text",
        x: reliable.map((row) => row.median_delivery_days),
        y: reliable.map((row) => row.mean_review_score),
        text: reliable.map((row) => row.state),
        textposition: "top center",
        textfont: { size: 11, color: chartColors.ink2 },
        marker: {
          color: chartColors.accentDeep,
          opacity: 0.75,
          size: reliable.map((row) => (48 * Math.sqrt(Math.max(0, row.gmv))) / maxSize),
          sizemode: "diameter",
          line: { width: 1, color: chartColors.surface },
        },
        customdata: reliable.map((row) => [
          `${row.state_name} (${row.state})`,
          formatMetricValue(row.gmv, "currency", "BRL"),
          formatNumber(row.delivered_orders),
          formatMetricValue(row.median_delivery_days, "days"),
          formatMetricValue(row.mean_review_score, "score"),
        ]),
        hovertemplate:
          "<b>%{customdata[0]}</b><br>GMV: %{customdata[1]}<br>Orders: %{customdata[2]}<br>Median delivery: %{customdata[3]}<br>Mean review: %{customdata[4]}<extra></extra>",
      },
    ];
  }, [reliable]);
  const layout = useMemo(
    () => ({
      margin: { l: 52, r: 24, t: 32, b: 48 },
      xaxis: { title: { text: "Median delivery days" }, rangemode: "tozero", showgrid: true },
      yaxis: { title: { text: "Mean review score" }, autorange: true, tickformat: ".1f" },
      hovermode: "closest",
      showlegend: false,
    }),
    [],
  );
  return (
    <Plot
      data={data}
      layout={layout}
      height={380}
      ariaLabel="Reliable states: median delivery days versus mean review score, labelled by state and sized by GMV"
    />
  );
}

function ReviewList({ title, rows }: { title: string; rows: CategoryScore[] }) {
  return (
    <Card title={title}>
      <ul className="list">
        {rows
          .filter((row) => row.reliable)
          .map((row) => (
            <li key={row.category}>
              <strong>{row.display_name}</strong>: {formatMetricValue(row.mean_review_score, "score")} · {formatNumber(row.orders)} orders
            </li>
          ))}
      </ul>
    </Card>
  );
}

function MarketsContent({ data }: { data: OlistMarkets }) {
  return (
    <div className="page">
      <PageHeader
        eyebrow="Olist marketplace · categories & regions"
        title="Category & regional scorecards"
        description="Compare market performance with Wilson 95% intervals for rates. Small groups are shown but not ranked; associations describe patterns across reliable groups."
      />
      <SectionTitle
        title="Category scorecards"
        description={`${formatNumber(data.categories.reliable_categories)} of ${formatNumber(data.categories.total_categories)} categories are reliable · minimum ${formatNumber(data.categories.min_orders)} orders · bubble diameter scales with the square root of GMV`}
      />
      <div className="grid grid-main-side">
        <ChartCard
          title="Delivery reliability & reviews by category"
          subtitle="Reliable categories only"
          chart={<CategoryScatter rows={data.categories.rows} />}
          table={<CategoryTable rows={data.categories.rows.filter((row) => row.reliable)} />}
        />
        <div className="stack" style={{ gap: 16 }}>
          <AssociationCard association={data.categories.association} />
          <ReviewList title="Best reviewed" rows={data.categories.best_reviewed} />
          <ReviewList title="Lowest reviewed" rows={data.categories.worst_reviewed} />
        </div>
      </div>
      <Card title="All categories" subtitle="Hover over rates to see Wilson 95% confidence intervals" footer={data.categories.note}>
        <CategoryTable rows={data.categories.rows} />
      </Card>
      <SectionTitle
        title="State scorecards"
        description={`${formatNumber(data.states.reliable_states)} of ${formatNumber(data.states.total_states)} states are reliable · minimum ${formatNumber(data.states.min_orders)} orders · bubble diameter scales with the square root of GMV`}
      />
      <div className="grid grid-main-side">
        <ChartCard
          title="Delivery time & reviews by state"
          subtitle="Reliable states only"
          chart={<StateScatter rows={data.states.rows} />}
          table={<StateTable rows={data.states.rows.filter((row) => row.reliable)} />}
        />
        <AssociationCard association={data.states.association} />
      </div>
      <Card title="All states" subtitle="Hover over rates to see Wilson 95% confidence intervals" footer={data.states.note}>
        <StateTable rows={data.states.rows} />
      </Card>
    </div>
  );
}

export function MarketsPage() {
  const query = useOlistMarkets();
  return <QueryBoundary query={query}>{(data) => <MarketsContent data={data} />}</QueryBoundary>;
}
