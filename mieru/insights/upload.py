import math
from typing import Any

import duckdb
import pandas as pd

from mieru.analytics.dashboard import build_trend
from mieru.insights.cards import Evidence, InsightCard, skipped
from mieru.metrics.upload import (
    POLICY_DEFAULTS,
    UPLOAD_METRICS_BY_ID,
    DatasetContext,
    Filters,
    classified_cte,
    compute_metric,
    orders_expression,
)
from src.analysis import two_proportion_tests

MIN_PRODUCTS: int = 10
MIN_CUSTOMERS: int = 50
MIN_PERIOD_ORDERS: int = 30
MIN_CATEGORY_LINES: int = 30
MIN_CATEGORY_RETURNS: int = 5
MIN_GROUP_ORDERS: int = 30
TREND_CHANGE_THRESHOLD: float = 0.10
PRODUCT_CONCENTRATION_THRESHOLD: float = 0.60
CUSTOMER_CONCENTRATION_THRESHOLD: float = 0.40
REGION_CONCENTRATION_THRESHOLD: float = 0.40
DISCOUNT_SHARE_THRESHOLD: float = 0.03
MARGIN_GAP_THRESHOLD: float = 0.10
CATEGORY_MIN_REVENUE_SHARE: float = 0.05
RETURN_RATE_MULTIPLIER: float = 1.5
CHANNEL_AOV_RATIO: float = 1.3
EXCLUSION_SHARE_THRESHOLD: float = 0.02
SIGNIFICANCE_LEVEL: float = 0.05
HIGH_CONFIDENCE_ROWS: int = 500
METHOD_NOTE: str = (
    "Deterministic rules over the same contributing rows as the dashboard, each with minimum-sample gates "
    "(and a significance test where groups are compared). No external AI service is used."
)

NO_FILTERS: Filters = Filters()


def frame(connection: duckdb.DuckDBPyConnection, context: DatasetContext, scopes: tuple[str, ...], select_sql: str, filters: Filters = NO_FILTERS) -> pd.DataFrame:
    cte_sql, parameters, _reasons = classified_cte(scopes, context, filters)
    return connection.execute(f"WITH {cte_sql.strip()} {select_sql}", parameters).df()


def confidence_for(rows: int) -> str:
    return "high" if rows >= HIGH_CONFIDENCE_ROWS else "medium"


def money(label: str, value: float | None, context: DatasetContext, metric_id: str | None = None) -> Evidence:
    return Evidence(label=label, value=value, unit="currency", currency=context.currency, metric_id=metric_id)


def line_revenue_ok(context: DatasetContext) -> bool:
    return context.capability("revenue")[0] and context.revenue_basis != "order_total"


def product_concentration(connection: duckdb.DuckDBPyConnection, context: DatasetContext, filters: Filters = NO_FILTERS) -> InsightCard | dict[str, str]:
    if not context.capability("products")[0] or not line_revenue_ok(context):
        return skipped("product_concentration", "Needs a product column and line-level revenue.")
    products = frame(
        connection,
        context,
        ("revenue",),
        "SELECT product_key, SUM(net_value) AS revenue, COUNT(*) AS lines FROM scoped WHERE contributes AND product_key IS NOT NULL GROUP BY 1 ORDER BY revenue DESC",
        filters=filters,
    )
    products = products[products["revenue"] > 0]
    if len(products) < MIN_PRODUCTS:
        return skipped("product_concentration", f"Fewer than {MIN_PRODUCTS} products with positive revenue.")
    total = float(products["revenue"].sum())
    top_count = max(1, math.ceil(0.2 * len(products)))
    top_share = float(products["revenue"].head(top_count).sum()) / total
    if top_share < PRODUCT_CONCENTRATION_THRESHOLD:
        return skipped("product_concentration", f"Top 20% of products hold {top_share:.0%} of revenue, below the {PRODUCT_CONCENTRATION_THRESHOLD:.0%} threshold.")
    leader = products.iloc[0]
    return InsightCard(
        insight_id="product_concentration",
        kind="info",
        confidence=confidence_for(int(products["lines"].sum())),
        finding=f"The top {top_count} of {len(products)} products ({top_count / len(products):.0%}) generate {top_share:.0%} of net revenue.",
        evidence=(
            Evidence("Share of revenue from the top 20% of products", top_share, "share"),
            money(f"Revenue from the #1 product ({leader['product_key']})", float(leader["revenue"]), context),
            Evidence("#1 product share of revenue", float(leader["revenue"]) / total, "share"),
        ),
        interpretation="Revenue depends on a small set of products; stock-outs or price changes on them move the whole business.",
        action="Prioritise availability, visibility and margin monitoring for the top products, and review whether long-tail items justify their cost.",
        limitations=("Measured over the whole uploaded period; the mix can shift by season.",),
        gates=(f"≥ {MIN_PRODUCTS} products", f"top-20% share ≥ {PRODUCT_CONCENTRATION_THRESHOLD:.0%}"),
    )


def revenue_trend(connection: duckdb.DuckDBPyConnection, context: DatasetContext, filters: Filters = NO_FILTERS) -> InsightCard | dict[str, str]:
    trend = build_trend(connection, context, filters)
    if not trend.get("available") or not trend.get("revenue_available"):
        return skipped("revenue_trend", "Needs readable dates and revenue.")
    complete = [point for point in trend["points"] if not point["is_partial"]]
    if len(complete) < 2:
        return skipped("revenue_trend", "Fewer than two complete periods.")
    current, previous = complete[-1], complete[-2]
    if current["orders"] < MIN_PERIOD_ORDERS or previous["orders"] < MIN_PERIOD_ORDERS:
        return skipped("revenue_trend", f"The last two complete periods need ≥ {MIN_PERIOD_ORDERS} {context.orders_label.lower()} each.")
    if not previous["revenue"]:
        return skipped("revenue_trend", "The previous period has no revenue.")
    change = (current["revenue"] - previous["revenue"]) / abs(previous["revenue"])
    if abs(change) < TREND_CHANGE_THRESHOLD:
        return skipped("revenue_trend", f"Revenue moved {change:+.0%} between the last two complete periods, below the ±{TREND_CHANGE_THRESHOLD:.0%} threshold.")
    evidence = [
        money(f"Revenue {current['period']}", current["revenue"], context, "net_revenue"),
        money(f"Revenue {previous['period']}", previous["revenue"], context, "net_revenue"),
        Evidence("Change vs previous complete period", change, "ratio"),
    ]
    limitations = ["Compares two consecutive complete periods; partial periods are excluded."]
    year_ago = next((point for point in complete if point["period"][:4] == str(int(current["period"][:4]) - 1) and point["period"][5:7] == current["period"][5:7]), None)
    if trend.get("granularity") == "month" and year_ago and year_ago["revenue"]:
        evidence.append(Evidence(f"Change vs same month last year ({year_ago['period'][:7]})", (current["revenue"] - year_ago["revenue"]) / abs(year_ago["revenue"]), "ratio"))
    else:
        limitations.append("No same-period-last-year data, so seasonality is not controlled for.")
    growing = change > 0
    return InsightCard(
        insight_id="revenue_trend",
        kind="opportunity" if growing else "risk",
        confidence=confidence_for(current["orders"] + previous["orders"]),
        finding=f"Net revenue {'rose' if growing else 'fell'} {abs(change):.0%} in {current['period']} versus {previous['period']}.",
        evidence=tuple(evidence),
        interpretation="A move of this size between consecutive complete periods is worth explaining before it is extrapolated.",
        action="Break the change down by category, channel and region on the dashboard filters to find where it came from."
        if growing
        else "Check which categories, channels or regions drove the decline using the dashboard filters, and compare with last year's season.",
        limitations=tuple(limitations),
        gates=(f"≥ {MIN_PERIOD_ORDERS} {context.orders_label.lower()} in each period", f"|change| ≥ {TREND_CHANGE_THRESHOLD:.0%}"),
    )


def category_returns(connection: duckdb.DuckDBPyConnection, context: DatasetContext, filters: Filters = NO_FILTERS) -> InsightCard | dict[str, str]:
    if not (context.capability("returns")[0] and context.capability("categories")[0]) or not line_revenue_ok(context):
        return skipped("category_returns", "Needs returns and a category column with line-level revenue.")
    categories = frame(
        connection,
        context,
        ("revenue",),
        "SELECT category, COUNT(*) FILTER (WHERE NOT is_return) AS sale_lines, COUNT(*) FILTER (WHERE is_return) AS return_lines, "
        "-SUM(net_value) FILTER (WHERE is_return) AS return_value FROM scoped WHERE contributes AND category IS NOT NULL GROUP BY 1",
        filters=filters,
    )
    eligible = categories[(categories["sale_lines"] >= MIN_CATEGORY_LINES)]
    total_sales = int(categories["sale_lines"].sum())
    total_returns = int(categories["return_lines"].sum())
    if eligible.empty or total_sales == 0 or total_returns < MIN_CATEGORY_RETURNS:
        return skipped("category_returns", f"Needs ≥ {MIN_CATEGORY_LINES} sales lines per category and ≥ {MIN_CATEGORY_RETURNS} returns.")
    overall_rate = total_returns / total_sales
    best: tuple[float, pd.Series, dict[str, Any]] | None = None
    for _index, row in eligible.iterrows():
        returns, sales = int(row["return_lines"]), int(row["sale_lines"])
        if returns < MIN_CATEGORY_RETURNS:
            continue
        rest_returns, rest_sales = total_returns - returns, total_sales - sales
        if rest_sales <= 0 or rest_returns <= 0:
            continue
        rate = returns / sales
        test = two_proportion_tests(returns, sales, rest_returns, rest_sales)
        if rate >= RETURN_RATE_MULTIPLIER * overall_rate and test["chi2_p_value"] < SIGNIFICANCE_LEVEL and (best is None or rate > best[0]):
            best = (rate, row, test)
    if best is None:
        return skipped("category_returns", "No category's share of returned lines is significantly above the rest (p < 0.05 and ≥ 1.5× overall).")
    rate, row, test = best
    return InsightCard(
        insight_id="category_returns",
        kind="risk",
        confidence="high" if int(row["sale_lines"]) >= HIGH_CONFIDENCE_ROWS else "medium",
        finding=f"'{row['category']}' has {rate:.1%} of its sales lines returned, {rate / overall_rate:.1f}× the overall {overall_rate:.1%}.",
        evidence=(
            Evidence("Returned lines ÷ sales lines", rate, "ratio"),
            Evidence("Overall returned lines ÷ sales lines", overall_rate, "ratio"),
            money("Value returned in this category", float(row["return_value"] or 0.0), context, "returns_value"),
            Evidence("χ² p-value vs other categories", float(test["chi2_p_value"]), "index"),
        ),
        interpretation="Returns in this category are unusually frequent, which erodes revenue and adds handling cost.",
        action="Review product descriptions, sizing, quality and packaging for this category, and check whether specific products drive the returns.",
        limitations=(
            "Counted in lines (needed for the significance test); the value-based return rate is on the Performance page.",
            "Returns are matched to the period they were recorded in, not to the original sale.",
        ),
        gates=(f"≥ {MIN_CATEGORY_LINES} sales lines", f"≥ {MIN_CATEGORY_RETURNS} returns", "χ² p < 0.05", f"≥ {RETURN_RATE_MULTIPLIER}× overall rate"),
    )


def discount_impact(connection: duckdb.DuckDBPyConnection, context: DatasetContext, filters: Filters = NO_FILTERS) -> InsightCard | dict[str, str]:
    if not context.capability("discounts")[0]:
        return skipped("discount_impact", "No discount column was recognised.")
    if not line_revenue_ok(context):
        return skipped("discount_impact", "Needs a single-currency, line-level revenue basis.")
    discounts = compute_metric(connection, UPLOAD_METRICS_BY_ID["discounts_value"], context, filters).value
    totals = frame(
        connection,
        context,
        ("revenue",),
        "SELECT SUM(net_value + COALESCE(discount_value, 0)) AS list_value FROM scoped WHERE contributes AND NOT is_return",
        filters=filters,
    )
    list_value = float(totals["list_value"].iloc[0]) if len(totals) and pd.notna(totals["list_value"].iloc[0]) else 0.0
    if not discounts or list_value <= 0:
        return skipped("discount_impact", "No discounts were recorded on contributing rows.")
    share = discounts / list_value
    if share < DISCOUNT_SHARE_THRESHOLD:
        return skipped("discount_impact", f"Discounts are {share:.1%} of list value, below the {DISCOUNT_SHARE_THRESHOLD:.0%} threshold.")
    evidence = [money("Total discounts", discounts, context, "discounts_value"), Evidence("Discount rate (discounts ÷ list value)", share, "share")]
    if context.capability("profit")[0]:
        margins = frame(
            connection,
            context,
            ("revenue", "cost"),
            "SELECT COALESCE(discount_value, 0) > 0 AS discounted, SUM(net_value - cost_value) / NULLIF(SUM(net_value), 0) AS margin, COUNT(*) AS lines "
            "FROM scoped WHERE contributes AND NOT is_return GROUP BY 1",
            filters=filters,
        )
        by_flag = {bool(row["discounted"]): row for _index, row in margins.iterrows()}
        if True in by_flag and False in by_flag and by_flag[True]["lines"] >= MIN_CATEGORY_LINES and by_flag[False]["lines"] >= MIN_CATEGORY_LINES:
            evidence.append(Evidence("Gross margin on discounted lines", float(by_flag[True]["margin"]), "ratio"))
            evidence.append(Evidence("Gross margin on full-price lines", float(by_flag[False]["margin"]), "ratio"))
    return InsightCard(
        insight_id="discount_impact",
        kind="info",
        confidence="medium",
        finding=f"Discounts gave away {share:.1%} of list value.",
        evidence=tuple(evidence),
        interpretation="Discounts are a material lever on revenue; their value depends on whether they create sales that would not have happened anyway.",
        action="Compare the volume and repeat behaviour of discounted vs full-price orders before extending promotions; cap discounts on low-margin products.",
        limitations=("Shows the cost of discounts, not their incremental effect (there is no control group in the data).",),
        gates=(f"discount share ≥ {DISCOUNT_SHARE_THRESHOLD:.0%}",),
    )


def low_margin_category(connection: duckdb.DuckDBPyConnection, context: DatasetContext, filters: Filters = NO_FILTERS) -> InsightCard | dict[str, str]:
    if not (context.capability("profit")[0] and context.capability("categories")[0]) or not line_revenue_ok(context):
        return skipped("low_margin_category", "Needs cost and category columns with single-currency, line-level revenue.")
    categories = frame(
        connection,
        context,
        ("revenue", "cost"),
        "SELECT category, SUM(net_value) AS revenue, SUM(net_value - cost_value) AS profit, COUNT(*) AS lines FROM scoped WHERE contributes AND category IS NOT NULL GROUP BY 1",
        filters=filters,
    )
    total_revenue = float(categories["revenue"].sum())
    if total_revenue <= 0 or len(categories) < 2:
        return skipped("low_margin_category", "Needs at least two categories with revenue.")
    categories["share"] = categories["revenue"] / total_revenue
    categories["margin"] = categories["profit"] / categories["revenue"]
    overall_margin = float(categories["profit"].sum()) / total_revenue
    eligible = categories[(categories["share"] >= CATEGORY_MIN_REVENUE_SHARE) & (categories["lines"] >= MIN_CATEGORY_LINES)]
    if eligible.empty:
        return skipped("low_margin_category", "No category meets the size gates.")
    worst = eligible.sort_values("margin").iloc[0]
    gap = overall_margin - float(worst["margin"])
    if gap < MARGIN_GAP_THRESHOLD:
        return skipped("low_margin_category", f"The lowest-margin category is only {gap:.0%} points below the average margin.")
    return InsightCard(
        insight_id="low_margin_category",
        kind="risk",
        confidence=confidence_for(int(worst["lines"])),
        finding=f"'{worst['category']}' earns a {float(worst['margin']):.0%} gross margin, {gap * 100:.0f} points below the {overall_margin:.0%} average.",
        evidence=(
            Evidence("Category gross margin", float(worst["margin"]), "ratio"),
            Evidence("Average gross margin", overall_margin, "ratio", metric_id="gross_margin"),
            Evidence("Category share of revenue", float(worst["share"]), "share"),
            money("Category gross profit", float(worst["profit"]), context),
        ),
        interpretation="A sizeable category with thin margins dilutes profitability even when its revenue looks healthy.",
        action="Review pricing, supplier costs and discount depth for this category; consider bundling it with higher-margin products.",
        limitations=("Uses the cost recorded in the file; overheads, shipping and payment fees are not included.",),
        gates=(f"≥ {CATEGORY_MIN_REVENUE_SHARE:.0%} revenue share", f"margin gap ≥ {MARGIN_GAP_THRESHOLD * 100:.0f} points"),
    )


def customer_concentration(connection: duckdb.DuckDBPyConnection, context: DatasetContext, filters: Filters = NO_FILTERS) -> list[InsightCard | dict[str, str]]:
    if not (context.capability("customers")[0] and context.capability("revenue")[0]) or context.revenue_basis == "order_total":
        return [skipped("customer_concentration", "Needs customer identifiers and line-level revenue.")]
    customers = frame(
        connection,
        context,
        ("revenue", "customer") + (() if context.grain == "transaction" else ("order",)),
        f"SELECT customer_id, SUM(net_value) AS revenue, {orders_expression(context)} AS orders FROM scoped WHERE contributes GROUP BY 1",
        filters=filters,
    )
    if len(customers) < MIN_CUSTOMERS:
        return [skipped("customer_concentration", f"Fewer than {MIN_CUSTOMERS} customers.")]
    results: list[InsightCard | dict[str, str]] = []
    positive = customers[customers["revenue"] > 0].sort_values("revenue", ascending=False)
    total = float(positive["revenue"].sum())
    top_count = max(1, math.ceil(0.1 * len(positive)))
    top_share = float(positive["revenue"].head(top_count).sum()) / total if total else 0.0
    if top_share >= CUSTOMER_CONCENTRATION_THRESHOLD:
        results.append(
            InsightCard(
                insight_id="customer_concentration",
                kind="risk",
                confidence=confidence_for(len(positive)),
                finding=f"The top 10% of customers ({top_count}) account for {top_share:.0%} of net revenue.",
                evidence=(Evidence("Revenue share of top 10% customers", top_share, "share"), Evidence("Customers with revenue", float(len(positive)), "count", metric_id="customers")),
                interpretation="Revenue relies on a small group of customers, so losing a few of them would be felt immediately.",
                action="Identify these customers and protect the relationship (service levels, loyalty benefits), while broadening acquisition.",
                limitations=("Customer identity depends on the customer column; guest checkouts may split one person into several IDs.",),
                gates=(f"≥ {MIN_CUSTOMERS} customers", f"top-10% share ≥ {CUSTOMER_CONCENTRATION_THRESHOLD:.0%}"),
            )
        )
    else:
        results.append(skipped("customer_concentration", f"Top 10% of customers hold {top_share:.0%} of revenue, below the {CUSTOMER_CONCENTRATION_THRESHOLD:.0%} threshold."))
    repeat_share = float((customers["orders"] >= 2).mean())
    results.append(
        InsightCard(
            insight_id="repeat_customers",
            kind="info",
            confidence=confidence_for(len(customers)),
            finding=f"{repeat_share:.0%} of customers placed two or more {context.orders_label.lower()} in this file.",
            evidence=(
                Evidence("Repeat customers", float(int((customers["orders"] >= 2).sum())), "count"),
                Evidence("Repeat-customer share", repeat_share, "share"),
                Evidence("Customers", float(len(customers)), "count", metric_id="customers"),
            ),
            interpretation="Repeat purchasing is the main driver of lifetime value; this share is the baseline to improve.",
            action="Track this share monthly; test post-purchase follow-ups or loyalty incentives against a holdout group.",
            limitations=("Customers who bought near the end of the file have had less time to return (right-censoring), so the share is a lower bound.",),
            gates=(f"≥ {MIN_CUSTOMERS} customers",),
        )
    )
    return results


def group_concentration(connection: duckdb.DuckDBPyConnection, context: DatasetContext, filters: Filters = NO_FILTERS) -> list[InsightCard | dict[str, str]]:
    results: list[InsightCard | dict[str, str]] = []
    revenue_ok = context.capability("revenue")[0] and context.revenue_basis != "order_total"
    if context.capability("regions")[0] and revenue_ok:
        regions = frame(
            connection,
            context,
            ("revenue",),
            f"SELECT {context.region_column} AS label, SUM(net_value) AS revenue FROM scoped WHERE contributes AND {context.region_column} IS NOT NULL GROUP BY 1 ORDER BY 2 DESC",
            filters=filters,
        )
        if len(regions) >= 3 and float(regions["revenue"].sum()) > 0:
            share = float(regions["revenue"].iloc[0]) / float(regions["revenue"].sum())
            if share >= REGION_CONCENTRATION_THRESHOLD:
                results.append(
                    InsightCard(
                        insight_id="region_concentration",
                        kind="info",
                        confidence="medium",
                        finding=f"{regions['label'].iloc[0]} generates {share:.0%} of net revenue across {len(regions)} regions.",
                        evidence=(Evidence("Top region share", share, "share"), money(f"Revenue in {regions['label'].iloc[0]}", float(regions['revenue'].iloc[0]), context)),
                        interpretation="Demand is geographically concentrated; delivery performance and marketing in this region matter disproportionately.",
                        action="Benchmark delivery times and conversion in the top region, and test targeted campaigns in under-represented regions.",
                        limitations=("Region comes from the file's region/state/country column and may reflect billing rather than delivery address.",),
                        gates=("≥ 3 regions", f"top share ≥ {REGION_CONCENTRATION_THRESHOLD:.0%}"),
                    )
                )
            else:
                results.append(skipped("region_concentration", f"Top region holds {share:.0%}, below {REGION_CONCENTRATION_THRESHOLD:.0%}."))
        else:
            results.append(skipped("region_concentration", "Needs at least three regions with revenue."))
    if context.capability("channels")[0] and revenue_ok and context.grain != "transaction":
        channels = frame(
            connection,
            context,
            ("revenue", "order"),
            f"SELECT channel, SUM(net_value) AS revenue, {orders_expression(context)} AS orders FROM scoped WHERE contributes AND channel IS NOT NULL GROUP BY 1",
            filters=filters,
        )
        channels = channels[channels["orders"] >= MIN_GROUP_ORDERS]
        if len(channels) >= 2:
            channels = channels.assign(aov=channels["revenue"] / channels["orders"]).sort_values("aov", ascending=False)
            high, low = channels.iloc[0], channels.iloc[-1]
            ratio = float(high["aov"]) / float(low["aov"]) if float(low["aov"]) > 0 else 0.0
            if ratio >= CHANNEL_AOV_RATIO:
                results.append(
                    InsightCard(
                        insight_id="channel_aov_gap",
                        kind="opportunity",
                        confidence=confidence_for(int(channels["orders"].sum())),
                        finding=f"Orders through '{high['channel']}' average {ratio:.1f}× the value of orders through '{low['channel']}'.",
                        evidence=(money(f"AOV · {high['channel']}", float(high["aov"]), context, "aov"), money(f"AOV · {low['channel']}", float(low["aov"]), context, "aov")),
                        interpretation="Channels attract different baskets; the gap shows where basket-building tactics could work.",
                        action=f"Test bundles, free-shipping thresholds or recommendations in '{low['channel']}' to close part of the gap.",
                        limitations=("Channels can differ in product mix and customer type, so the gap is descriptive, not causal.",),
                        gates=(f"≥ {MIN_GROUP_ORDERS} orders per channel", f"AOV ratio ≥ {CHANNEL_AOV_RATIO}"),
                    )
                )
            else:
                results.append(skipped("channel_aov_gap", f"Channel AOVs differ by only {ratio:.2f}×."))
        else:
            results.append(skipped("channel_aov_gap", f"Needs at least two channels with ≥ {MIN_GROUP_ORDERS} orders."))
    return results


def data_quality(connection: duckdb.DuckDBPyConnection, context: DatasetContext, filters: Filters = NO_FILTERS) -> InsightCard | dict[str, str]:
    metric = UPLOAD_METRICS_BY_ID["net_revenue" if context.capability("revenue")[0] else "orders"]
    cleaned = compute_metric(connection, metric, context, filters)
    raw = compute_metric(connection, metric, context, filters, {key: False for key in POLICY_DEFAULTS})
    counts = cleaned.record_counts
    if counts is None or counts.input_records == 0:
        return skipped("data_quality", "No rows to assess.")
    share = counts.excluded_total / counts.input_records
    if share < EXCLUSION_SHARE_THRESHOLD:
        return skipped("data_quality", f"Only {share:.1%} of rows were excluded.")
    top_reason = max(counts.excluded, key=lambda item: item.records)
    delta = None if cleaned.value is None or raw.value is None else cleaned.value - raw.value
    return InsightCard(
        insight_id="data_quality",
        kind="quality",
        confidence="high",
        finding=f"{counts.excluded_total:,} of {counts.input_records:,} rows ({share:.1%}) were excluded from {cleaned.definition.label.lower()}; the largest reason is {top_reason.label.lower()}.",
        evidence=(
            Evidence("Excluded rows", float(counts.excluded_total), "count"),
            Evidence("Excluded share", share, "share"),
            Evidence(f"Change in {cleaned.definition.label.lower()} from cleaning", delta, metric.unit, cleaned.currency, metric.metric_id),
        ),
        interpretation="Reported figures depend on these cleaning decisions; each one is reversible on the Data Quality page.",
        action="Fix the issue at the source system if possible (e.g. duplicate exports, unreadable prices) so future files need less cleaning.",
        limitations=("Unreadable values are excluded rather than estimated.",),
        gates=(f"excluded share ≥ {EXCLUSION_SHARE_THRESHOLD:.0%}",),
    )


def build_upload_insights(connection: duckdb.DuckDBPyConnection, context: DatasetContext, filters: Filters = NO_FILTERS) -> dict[str, Any]:
    outcomes: list[InsightCard | dict[str, str]] = [
        revenue_trend(connection, context, filters),
        product_concentration(connection, context, filters),
        category_returns(connection, context, filters),
        low_margin_category(connection, context, filters),
        discount_impact(connection, context, filters),
        *customer_concentration(connection, context, filters),
        *group_concentration(connection, context, filters),
        data_quality(connection, context, filters),
    ]
    cards = [outcome.to_dict() for outcome in outcomes if isinstance(outcome, InsightCard)]
    skipped_rules = [outcome for outcome in outcomes if isinstance(outcome, dict)]
    return {"cards": cards, "skipped": skipped_rules, "rules_evaluated": len(outcomes), "method": METHOD_NOTE}
