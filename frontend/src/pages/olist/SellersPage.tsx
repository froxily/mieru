import { useMemo } from "react";
import type { OlistSellers, TierRow } from "../../api/types";
import { Plot } from "../../charts/Plot";
import { chartColors } from "../../charts/theme";
import { Card, ChartCard } from "../../components/Card";
import { DataTable } from "../../components/DataTable";
import { KpiCard } from "../../components/KpiCard";
import { PageHeader, SectionTitle } from "../../components/PageHeader";
import { QueryBoundary } from "../../components/QueryBoundary";
import { Callout } from "../../components/States";
import { formatCurrency, formatNumber, formatPercent } from "../../lib/format";
import { useOlistSellers } from "../../features/olist/queries";

const TIER_COLORS = ["#104281", "#2a78d6", "#86b6ef"];

function LorenzChart({ sellers }: { sellers: OlistSellers }) {
  const top50 = sellers.pareto.sellers_for_50pct.seller_share_pct;
  const top80 = sellers.pareto.sellers_for_80pct.seller_share_pct;
  const data = useMemo(() => {
    const x = sellers.lorenz.seller_share.map((value) => value * 100);
    const y = sellers.lorenz.gmv_share.map((value) => value * 100);
    return [
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
        x,
        y,
        name: "Seller GMV Lorenz curve",
        line: { color: chartColors.accent, width: 2.6 },
        fill: "tonexty",
        fillcolor: "rgba(42,120,214,0.10)",
        hovertemplate: "Bottom %{x:.1f}% of sellers<br>generate %{y:.1f}% of GMV<extra></extra>",
      },
      {
        type: "scatter",
        mode: "markers+text",
        x: [100 - top50, 100 - top80],
        y: [50, 20],
        marker: { size: 10, color: chartColors.ink, line: { color: "#fff", width: 2 } },
        text: [`Top ${top50.toFixed(1)}% → 50% of GMV`, `Top ${top80.toFixed(1)}% → 80% of GMV`],
        textposition: ["middle left", "middle left"],
        textfont: { size: 12, color: chartColors.ink },
        hoverinfo: "skip",
        showlegend: false,
      },
    ];
  }, [sellers, top50, top80]);
  const layout = useMemo(
    () => ({
      margin: { l: 56, r: 16, t: 36, b: 48 },
      showlegend: true,
      legend: { orientation: "h", x: 0, y: 1, yanchor: "bottom" },
      xaxis: { range: [0, 100], ticksuffix: "%", title: { text: "Cumulative share of sellers (smallest → largest)" }, showgrid: true },
      yaxis: { range: [0, 100], ticksuffix: "%", title: { text: "Cumulative share of GMV" } },
      annotations: [
        {
          x: 4,
          y: 92,
          xanchor: "left",
          showarrow: false,
          align: "left",
          text: `<b>Gini ${sellers.gini.value.toFixed(3)}</b><br>95% CI ${sellers.gini.ci[0].toFixed(3)}–${sellers.gini.ci[1].toFixed(3)}`,
          font: { size: 12, color: chartColors.ink },
        },
      ],
      hovermode: "closest",
    }),
    [sellers],
  );
  return <Plot data={data} layout={layout} height={420} ariaLabel="Seller GMV Lorenz curve" />;
}

function TierBreachChart({ tiers }: { tiers: TierRow[] }) {
  const data = useMemo(
    () => [
      {
        type: "bar",
        x: tiers.map((tier) => tier.pareto_tier.replace(" Sellers", "")),
        y: tiers.map((tier) => tier.sla_breach.rate_pct),
        marker: { color: TIER_COLORS },
        error_y: {
          type: "data",
          symmetric: false,
          array: tiers.map((tier) => (tier.sla_breach.ci_high_pct ?? 0) - (tier.sla_breach.rate_pct ?? 0)),
          arrayminus: tiers.map((tier) => (tier.sla_breach.rate_pct ?? 0) - (tier.sla_breach.ci_low_pct ?? 0)),
          color: chartColors.ink2,
          thickness: 1.2,
          width: 4,
        },
        text: tiers.map((tier) => `${tier.sla_breach.rate_pct?.toFixed(1)}%`),
        textposition: "outside",
        cliponaxis: false,
        customdata: tiers.map((tier) => [tier.sellers, tier.gmv_share_pct, tier.seller_orders]),
        hovertemplate:
          "<b>%{x}</b><br>SLA breach %{y:.2f}%<br>%{customdata[0]:,} sellers · %{customdata[1]:.1f}% of GMV<br>%{customdata[2]:,} seller-orders<extra></extra>",
      },
    ],
    [tiers],
  );
  const layout = useMemo(() => ({ margin: { l: 44, r: 8, t: 24, b: 36 }, yaxis: { ticksuffix: "%", rangemode: "tozero", range: [0, 9] }, bargap: 0.45 }), []);
  return <Plot data={data} layout={layout} height={280} ariaLabel="SLA breach rate by seller Pareto tier" />;
}

function SizeDistributionChart({ bands }: { bands: OlistSellers["size_distribution"] }) {
  const data = useMemo(
    () => [
      {
        type: "bar",
        x: bands.map((band) => band.band),
        y: bands.map((band) => band.sellers),
        marker: { color: chartColors.accentLight },
        text: bands.map((band) => formatNumber(band.sellers)),
        textposition: "outside",
        cliponaxis: false,
        hovertemplate: "<b>%{x}</b><br>%{y:,} sellers<extra></extra>",
      },
    ],
    [bands],
  );
  const layout = useMemo(() => ({ margin: { l: 44, r: 8, t: 20, b: 36 }, yaxis: { rangemode: "tozero" }, bargap: 0.35 }), []);
  return <Plot data={data} layout={layout} height={280} ariaLabel="Sellers by lifetime GMV band" />;
}

function SellersContent({ data }: { data: OlistSellers }) {
  const correlation = data.quality_correlation;
  return (
    <div className="page">
      <PageHeader
        eyebrow="Olist marketplace · supply side"
        title="Sellers & GMV concentration"
        description="A small group of sellers drives most of the marketplace's value. Concentration is measured with an exact Lorenz/Gini calculation and a bootstrap confidence interval."
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
          label="Sellers generating 50% of GMV"
          value={data.pareto.sellers_for_50pct.seller_share_pct / 100}
          unit="share"
          context={`${formatNumber(data.pareto.sellers_for_50pct.sellers)} sellers`}
          stagger={3}
        />
      </div>

      <div className="grid grid-main-side">
        <ChartCard
          title="Seller GMV Lorenz curve"
          subtitle="The further the curve bows from the dotted line, the more concentrated GMV is"
          chart={<LorenzChart sellers={data} />}
          table={
            <DataTable
              rows={data.lorenz.seller_share.map((share, index) => ({ share, gmv: data.lorenz.gmv_share[index] ?? 0, index }))}
              rowKey={(row) => String(row.index)}
              maxHeight={420}
              columns={[
                { key: "share", header: "Cumulative sellers", align: "right", render: (row) => formatPercent(row.share) },
                { key: "gmv", header: "Cumulative GMV", align: "right", render: (row) => formatPercent(row.gmv) },
              ]}
            />
          }
        />
        <div className="stack" style={{ gap: 16 }}>
          <ChartCard
            title="SLA breach rate by Pareto tier"
            subtitle={`Wilson 95% CIs · χ² p = ${data.tier_breach_test.p_value.toFixed(4)}`}
            chart={<TierBreachChart tiers={data.tiers} />}
            table={
              <DataTable
                rows={data.tiers}
                rowKey={(row) => row.pareto_tier}
                columns={[
                  { key: "tier", header: "Tier", render: (row) => row.pareto_tier },
                  { key: "breach", header: "Breach", align: "right", render: (row) => `${row.sla_breach.rate_pct?.toFixed(2)}%` },
                  { key: "n", header: "Seller-orders", align: "right", render: (row) => formatNumber(row.seller_orders) },
                ]}
              />
            }
          />
          <Callout tone="info" title="Scale has not bought reliability">
            Top-tier sellers breach the delivery promise slightly <em>more</em> often than the long tail. Across {formatNumber(correlation.sellers)} sellers
            with ≥{correlation.min_orders_per_seller} orders, a seller's breach rate and rating move together (Spearman ρ ={" "}
            {correlation.spearman_rho_breach_rate_vs_mean_review.toFixed(2)}).
          </Callout>
        </div>
      </div>

      <SectionTitle title="Seller unit economics by tier" description="Tiers by GMV rank: top 10%, next 40%, bottom 50%." />
      <Card stagger={1}>
        <DataTable
          rows={data.tiers}
          rowKey={(row) => row.pareto_tier}
          columns={[
            { key: "tier", header: "Tier", render: (row) => <strong>{row.pareto_tier}</strong> },
            { key: "sellers", header: "Sellers", align: "right", sortValue: (row) => row.sellers, render: (row) => formatNumber(row.sellers) },
            { key: "share", header: "GMV share", align: "right", sortValue: (row) => row.gmv_share_pct, render: (row) => `${row.gmv_share_pct.toFixed(1)}%` },
            {
              key: "orders",
              header: "Orders / seller",
              align: "right",
              sortValue: (row) => row.orders_per_seller,
              render: (row) => formatNumber(row.orders_per_seller, 1),
            },
            {
              key: "median",
              header: "Median seller GMV",
              align: "right",
              sortValue: (row) => row.median_seller_gmv_brl,
              render: (row) => formatCurrency(row.median_seller_gmv_brl, "BRL"),
            },
            {
              key: "aov",
              header: "GMV / seller-order",
              align: "right",
              sortValue: (row) => row.gmv_per_seller_order_brl,
              render: (row) => formatCurrency(row.gmv_per_seller_order_brl, "BRL", { fractionDigits: 2 }),
            },
            {
              key: "review",
              header: "Mean review",
              align: "right",
              sortValue: (row) => row.order_weighted_mean_review_score,
              render: (row) => row.order_weighted_mean_review_score.toFixed(2),
            },
          ]}
        />
      </Card>

      <div className="grid grid-main-side">
        <Card title="Top 15 sellers by GMV" subtitle="Seller IDs truncated" stagger={2}>
          <DataTable
            rows={data.top_sellers}
            rowKey={(row) => row.seller_label}
            columns={[
              { key: "rank", header: "#", align: "right", sortValue: (row) => row.seller_rank, render: (row) => String(row.seller_rank) },
              { key: "seller", header: "Seller", render: (row) => row.seller_label },
              { key: "gmv", header: "GMV", align: "right", sortValue: (row) => row.seller_gmv, render: (row) => formatCurrency(row.seller_gmv, "BRL") },
              { key: "orders", header: "Orders", align: "right", sortValue: (row) => row.total_orders, render: (row) => formatNumber(row.total_orders) },
              { key: "breach", header: "Breach", align: "right", sortValue: (row) => row.sla_breach_rate, render: (row) => formatPercent(row.sla_breach_rate) },
              {
                key: "cum",
                header: "Cumulative share",
                align: "right",
                sortValue: (row) => row.cumulative_gmv_share,
                render: (row) => formatPercent(row.cumulative_gmv_share),
              },
            ]}
          />
        </Card>
        <ChartCard
          title="Sellers by lifetime GMV"
          subtitle="Most sellers are small"
          chart={<SizeDistributionChart bands={data.size_distribution} />}
          table={
            <DataTable
              rows={data.size_distribution}
              rowKey={(row) => row.band}
              columns={[
                { key: "band", header: "GMV band" },
                { key: "sellers", header: "Sellers", align: "right", render: (row) => formatNumber(row.sellers) },
              ]}
            />
          }
        />
      </div>
    </div>
  );
}

export function SellersPage() {
  const query = useOlistSellers();
  return <QueryBoundary query={query}>{(data) => <SellersContent data={data} />}</QueryBoundary>;
}
