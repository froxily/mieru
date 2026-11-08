import math
from typing import Any

import duckdb
import numpy as np

from mieru.metrics.definitions import as_float
from mieru.metrics.upload import LINE_BASES, DatasetContext, Filters, classified_cte, revenue_expression
from src.analysis import lorenz_gini

GROUP_LIMIT: int = 15
LOWEST_MARGIN_LIMIT: int = 5
MATERIAL_REVENUE_SHARE: float = 0.01
SMALL_SAMPLE_ROWS: int = 30
PARETO_STEPS: int = 100
MIN_CONCENTRATION_ITEMS: int = 5
VALUE_TOLERANCE: float = 0.005
NOT_SPECIFIED: str = "(not specified)"
GROUP_DIMENSIONS: dict[str, tuple[str, str]] = {
    "categories": ("category", "categories"),
    "products": ("product_key", "products"),
    "channels": ("channel", "channels"),
    "regions": ("region_dimension", "regions"),
}
ORDER_TOTAL_REASON: str = "Revenue is recorded as order totals, so it cannot be split by line into gross sales, discounts, returns or cost."


def number(value: Any) -> float:
    converted = as_float(value)
    return 0.0 if converted is None else converted


def scoped_query(connection: duckdb.DuckDBPyConnection, context: DatasetContext, filters: Filters, scopes: tuple[str, ...], body: str) -> list[dict[str, Any]]:
    cte_sql, parameters, _reasons = classified_cte(scopes, context, filters)
    cursor = connection.execute(f"WITH {cte_sql.strip()}\n{body}", parameters)
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def line_revenue_gate(context: DatasetContext, capability: str | None = None) -> tuple[bool, str | None]:
    available, reason = context.capability("revenue")
    if not available:
        return False, reason
    if context.revenue_basis not in LINE_BASES:
        return False, ORDER_TOTAL_REASON
    if capability is not None:
        return context.capability(capability)
    return True, None


def dimension_column(context: DatasetContext, key: str) -> str:
    column = GROUP_DIMENSIONS[key][0]
    return context.region_column if column == "region_dimension" else column


def available_dimensions(context: DatasetContext) -> list[str]:
    return [key for key, (_column, capability) in GROUP_DIMENSIONS.items() if context.capability(capability)[0]]


def build_bridge(connection: duckdb.DuckDBPyConnection, context: DatasetContext, filters: Filters) -> dict[str, Any]:
    available, reason = line_revenue_gate(context)
    if not available:
        return {"available": False, "reason": reason}
    row = scoped_query(
        connection,
        context,
        filters,
        ("revenue",),
        """SELECT
    SUM(signed_value) FILTER (WHERE contributes AND NOT is_return) AS gross_sales,
    SUM(signed_value - net_value) FILTER (WHERE contributes AND NOT is_return) AS discounts_deducted,
    SUM(discount_value) FILTER (WHERE contributes AND NOT is_return) AS discounts_recorded,
    -SUM(net_value) FILTER (WHERE contributes AND is_return) AS returns_value,
    SUM(net_value) FILTER (WHERE contributes) AS net_revenue,
    SUM(cost_value) FILTER (WHERE contributes) AS cost_value,
    COUNT(*) FILTER (WHERE contributes) AS contributing_rows,
    COUNT(*) FILTER (WHERE contributes AND is_return) AS return_rows,
    COUNT(*) FILTER (WHERE contributes AND cost_value IS NULL) AS rows_without_cost,
    COUNT(*) FILTER (WHERE contributes AND negative_unverified) AS unverified_negative_rows
FROM scoped""",
    )[0]
    gross_sales = number(row["gross_sales"])
    discounts_deducted = number(row["discounts_deducted"])
    discounts_recorded = number(row["discounts_recorded"])
    returns_value = number(row["returns_value"])
    net_revenue = number(row["net_revenue"])
    steps: list[dict[str, Any]] = [{"label": "Gross sales", "value": gross_sales, "kind": "total", "metric_id": "gross_sales"}]
    notes: list[str] = []
    if abs(discounts_deducted) > VALUE_TOLERANCE:
        steps.append({"label": "Discounts", "value": -discounts_deducted, "kind": "decrease", "metric_id": "discounts_value"})
    elif abs(discounts_recorded) > VALUE_TOLERANCE:
        steps[0]["label"] = "Sales after discounts"
        notes.append(
            f"Discounts of {discounts_recorded:,.2f} were recorded, but the amount column already has them deducted, so they are not subtracted again."
        )
    if abs(returns_value) > VALUE_TOLERANCE:
        steps.append({"label": "Returns & credits", "value": -returns_value, "kind": "decrease", "metric_id": "returns_value"})
    elif context.capability("returns")[0]:
        notes.append("No returns or credits fall inside the current filters.")
    steps.append({"label": "Net revenue", "value": net_revenue, "kind": "total", "metric_id": "net_revenue"})
    profit_available = context.capability("profit")[0]
    contributing_rows = int(row["contributing_rows"])
    rows_without_cost = int(row["rows_without_cost"])
    if profit_available and contributing_rows and rows_without_cost == 0:
        cost_value = number(row["cost_value"])
        steps.append({"label": "Cost of goods", "value": -cost_value, "kind": "decrease", "metric_id": None})
        steps.append({"label": "Gross profit", "value": net_revenue - cost_value, "kind": "total", "metric_id": "gross_profit"})
    elif profit_available and contributing_rows:
        covered = 1 - rows_without_cost / contributing_rows
        notes.append(f"Cost is recorded on {covered:.0%} of contributing rows, so profit appears in the profitability section for those rows only.")
    if int(row["unverified_negative_rows"]):
        notes.append(
            f"{int(row['unverified_negative_rows']):,} negative amounts without a return marker are kept as recorded inside gross sales (meaning unverified)."
        )
    residual = gross_sales - discounts_deducted - returns_value - net_revenue
    return {
        "available": True,
        "currency": context.currency,
        "steps": steps,
        "gross_sales": gross_sales,
        "discounts_deducted": discounts_deducted,
        "discounts_recorded": discounts_recorded,
        "returns_value": returns_value,
        "net_revenue": net_revenue,
        "contributing_rows": contributing_rows,
        "return_rows": int(row["return_rows"]),
        "reconciles": abs(residual) <= VALUE_TOLERANCE + 1e-9 * abs(net_revenue),
        "identity": "Gross sales − discounts deducted − returns & credits = net revenue",
        "notes": notes,
    }


def group_rows(
    connection: duckdb.DuckDBPyConnection, context: DatasetContext, filters: Filters, scopes: tuple[str, ...], key: str, measures: str, order_by: str
) -> list[dict[str, Any]]:
    column = dimension_column(context, key)
    return scoped_query(
        connection,
        context,
        filters,
        scopes,
        f"""SELECT COALESCE(CAST({column} AS VARCHAR), '{NOT_SPECIFIED}') AS label,
    {measures}
FROM scoped
WHERE contributes
GROUP BY 1
ORDER BY {order_by}, label""",
    )


def build_profitability(connection: duckdb.DuckDBPyConnection, context: DatasetContext, filters: Filters) -> dict[str, Any]:
    available, reason = line_revenue_gate(context, "profit")
    if not available:
        return {"available": False, "reason": reason}
    scopes = ("revenue", "cost")
    measures = """SUM(net_value) AS revenue,
    SUM(cost_value) AS cost,
    SUM(net_value - cost_value) AS gross_profit,
    COUNT(*) AS rows"""
    overall = scoped_query(connection, context, filters, scopes, f"SELECT {measures} FROM scoped WHERE contributes")[0]
    coverage = scoped_query(
        connection,
        context,
        filters,
        ("revenue",),
        "SELECT SUM(net_value) FILTER (WHERE contributes) AS revenue, COUNT(*) FILTER (WHERE contributes) AS rows, "
        "COUNT(*) FILTER (WHERE contributes AND cost_value IS NOT NULL) AS rows_with_cost FROM scoped",
    )[0]
    revenue = number(overall["revenue"])
    gross_profit = number(overall["gross_profit"])
    all_revenue = number(coverage["revenue"])
    groups: dict[str, Any] = {}
    for key in available_dimensions(context):
        rows = group_rows(connection, context, filters, scopes, key, measures, "gross_profit DESC NULLS LAST")
        records = [
            {
                "label": str(item["label"]),
                "revenue": number(item["revenue"]),
                "cost": number(item["cost"]),
                "gross_profit": number(item["gross_profit"]),
                "margin": number(item["gross_profit"]) / number(item["revenue"]) if number(item["revenue"]) > 0 else None,
                "revenue_share": number(item["revenue"]) / revenue if revenue > 0 else None,
                "rows": int(item["rows"]),
            }
            for item in rows
        ]
        material = [record for record in records if record["margin"] is not None and (record["revenue_share"] or 0) >= MATERIAL_REVENUE_SHARE]
        groups[key] = {
            "rows": records[:GROUP_LIMIT],
            "lowest_margin": sorted(material, key=lambda record: (record["margin"], record["label"]))[:LOWEST_MARGIN_LIMIT],
            "loss_making_groups": sum(1 for record in records if record["gross_profit"] < -VALUE_TOLERANCE),
            "total_groups": len(records),
        }
    return {
        "available": True,
        "currency": context.currency,
        "revenue": revenue,
        "cost": number(overall["cost"]),
        "gross_profit": gross_profit,
        "margin": gross_profit / revenue if revenue > 0 else None,
        "rows": int(overall["rows"]),
        "cost_coverage": {
            "rows_with_cost": int(coverage["rows_with_cost"]),
            "contributing_rows": int(coverage["rows"]),
            "revenue_share": revenue / all_revenue if all_revenue > 0 else None,
        },
        "groups": groups,
        "note": "Profit = net revenue − recorded cost on rows that have a cost; it is never estimated for rows without one. Returned items reverse their cost.",
    }


def build_returns(connection: duckdb.DuckDBPyConnection, context: DatasetContext, filters: Filters) -> dict[str, Any]:
    available, reason = line_revenue_gate(context, "returns")
    if not available:
        return {"available": False, "reason": reason}
    measures = """SUM(signed_value) FILTER (WHERE NOT is_return) AS gross_sales,
    SUM(net_value) FILTER (WHERE NOT is_return) AS net_sales,
    -SUM(net_value) FILTER (WHERE is_return) AS returns_value,
    COUNT(*) FILTER (WHERE NOT is_return) AS sale_rows,
    COUNT(*) FILTER (WHERE is_return) AS return_rows"""
    overall = scoped_query(connection, context, filters, ("revenue",), f"SELECT {measures} FROM scoped WHERE contributes")[0]
    gross_sales = number(overall["gross_sales"])
    net_sales = number(overall["net_sales"])
    returns_value = number(overall["returns_value"])
    groups: dict[str, Any] = {}
    for key in available_dimensions(context):
        rows = group_rows(connection, context, filters, ("revenue",), key, measures, "returns_value DESC NULLS LAST, gross_sales DESC NULLS LAST")
        records = []
        for item in rows:
            group_net_sales = number(item["net_sales"])
            group_returns = number(item["returns_value"])
            records.append(
                {
                    "label": str(item["label"]),
                    "gross_sales": number(item["gross_sales"]),
                    "net_sales": group_net_sales,
                    "returns_value": group_returns,
                    "return_rate": group_returns / group_net_sales if group_net_sales > 0 else None,
                    "sale_rows": int(item["sale_rows"]),
                    "return_rows": int(item["return_rows"]),
                    "small_sample": int(item["sale_rows"]) < SMALL_SAMPLE_ROWS,
                }
            )
        groups[key] = {"rows": records[:GROUP_LIMIT], "total_groups": len(records), "groups_with_returns": sum(1 for record in records if record["return_rows"])}
    return {
        "available": True,
        "currency": context.currency,
        "gross_sales": gross_sales,
        "net_sales": net_sales,
        "returns_value": returns_value,
        "return_rate": returns_value / net_sales if net_sales > 0 else None,
        "sale_rows": int(overall["sale_rows"]),
        "return_rows": int(overall["return_rows"]),
        "groups": groups,
        "note": f"Return rate = returns & credits ÷ sales after discounts (before returns); both sides are net of line discounts. Rates on groups with fewer than {SMALL_SAMPLE_ROWS} sale rows are marked as small samples.",
    }


def build_discounts(connection: duckdb.DuckDBPyConnection, context: DatasetContext, filters: Filters) -> dict[str, Any]:
    available, reason = line_revenue_gate(context, "discounts")
    if not available:
        return {"available": False, "reason": reason}
    measures = """SUM(COALESCE(discount_value, 0)) FILTER (WHERE NOT is_return) AS discount_value,
    SUM(net_value + COALESCE(discount_value, 0)) FILTER (WHERE NOT is_return) AS list_value,
    COUNT(*) FILTER (WHERE NOT is_return AND discount_value > 0) AS discounted_rows,
    COUNT(*) FILTER (WHERE NOT is_return) AS sale_rows"""

    def summarize(item: dict[str, Any]) -> dict[str, Any]:
        discount_value = number(item["discount_value"])
        list_value = number(item["list_value"])
        sale_rows = int(item["sale_rows"])
        return {
            "discount_value": discount_value,
            "list_value": list_value,
            "discount_rate": discount_value / list_value if list_value > 0 else None,
            "discounted_rows": int(item["discounted_rows"]),
            "sale_rows": sale_rows,
            "discounted_row_share": int(item["discounted_rows"]) / sale_rows if sale_rows else None,
        }

    overall = summarize(scoped_query(connection, context, filters, ("revenue",), f"SELECT {measures} FROM scoped WHERE contributes")[0])
    groups: dict[str, Any] = {}
    for key in available_dimensions(context):
        rows = group_rows(connection, context, filters, ("revenue",), key, measures, "discount_value DESC NULLS LAST")
        records = [{"label": str(item["label"]), **summarize(item)} for item in rows]
        groups[key] = {"rows": records[:GROUP_LIMIT], "total_groups": len(records)}
    trend: dict[str, Any] = {"available": False, "reason": context.capability("trend")[1]}
    if context.capability("trend")[0]:
        points = scoped_query(
            connection,
            context,
            filters,
            ("revenue", "date"),
            f"""SELECT CAST(date_trunc('month', order_ts) AS DATE) AS period, {measures}
FROM scoped
WHERE contributes
GROUP BY 1
ORDER BY 1""",
        )
        trend = {
            "available": len(points) >= 2,
            "reason": None if len(points) >= 2 else "Fewer than two months have discounted sales data.",
            "points": [{"period": item["period"].isoformat(), **summarize(item)} for item in points],
            "note": "Monthly view uses rows with a valid date.",
        }
    margin_split: dict[str, Any] | None = None
    if context.capability("profit")[0]:
        split = scoped_query(
            connection,
            context,
            filters,
            ("revenue", "cost"),
            """SELECT COALESCE(discount_value, 0) > 0 AS discounted,
    SUM(net_value) AS revenue,
    SUM(net_value - cost_value) AS gross_profit,
    COUNT(*) AS rows
FROM scoped
WHERE contributes AND NOT is_return
GROUP BY 1""",
        )
        by_flag = {bool(item["discounted"]): item for item in split}
        if True in by_flag and False in by_flag:
            margin_split = {
                label: {
                    "revenue": number(by_flag[flag]["revenue"]),
                    "gross_profit": number(by_flag[flag]["gross_profit"]),
                    "margin": number(by_flag[flag]["gross_profit"]) / number(by_flag[flag]["revenue"]) if number(by_flag[flag]["revenue"]) > 0 else None,
                    "rows": int(by_flag[flag]["rows"]),
                }
                for label, flag in (("discounted", True), ("full_price", False))
            }
    deducted = scoped_query(
        connection, context, filters, ("revenue",), "SELECT SUM(signed_value - net_value) FILTER (WHERE contributes AND NOT is_return) AS deducted FROM scoped"
    )[0]["deducted"]
    return {
        "available": True,
        "currency": context.currency,
        **overall,
        "treatment": "deducted" if abs(number(deducted)) > VALUE_TOLERANCE else "already_net",
        "groups": groups,
        "trend": trend,
        "margin_split": margin_split,
        "note": "Discount rate = discounts ÷ list value (net sales value + discounts) on contributing sales rows.",
    }


def pareto_summary(values: np.ndarray, labels: list[str] | None, item_label: str) -> dict[str, Any]:
    positive_mask = values > 0
    positive = values[positive_mask]
    excluded = int((~positive_mask).sum())
    if len(positive) < MIN_CONCENTRATION_ITEMS:
        return {"available": False, "reason": f"At least {MIN_CONCENTRATION_ITEMS} {item_label} with positive revenue are needed."}
    order = np.argsort(-positive, kind="stable")
    ranked = positive[order]
    total = float(ranked.sum())
    cumulative = np.cumsum(ranked) / total
    count = len(ranked)

    def share_of_top(fraction: float) -> float:
        return float(cumulative[max(1, math.ceil(fraction * count)) - 1])

    def items_for(share: float) -> int:
        return int(np.searchsorted(cumulative, share - 1e-12) + 1)

    curve = [{"item_share": 0.0, "revenue_share": 0.0}]
    if count <= PARETO_STEPS:
        curve += [{"item_share": (index + 1) / count, "revenue_share": float(cumulative[index])} for index in range(count)]
    else:
        for step in range(1, PARETO_STEPS + 1):
            index = max(1, math.ceil(step / PARETO_STEPS * count)) - 1
            curve.append({"item_share": step / PARETO_STEPS, "revenue_share": float(cumulative[index])})
    top_items = None
    if labels is not None:
        positive_labels = [label for label, keep in zip(labels, positive_mask) if keep]
        top_items = [{"label": positive_labels[int(index)], "revenue": float(positive[int(index)]), "share": float(positive[int(index)] / total)} for index in order[:5]]
    return {
        "available": True,
        "items": count,
        "excluded_non_positive": excluded,
        "revenue_total": total,
        "top_10pct_share": share_of_top(0.10),
        "top_20pct_share": share_of_top(0.20),
        "items_for_50pct": items_for(0.5),
        "items_for_80pct": items_for(0.8),
        "gini": float(lorenz_gini(positive)),
        "curve": curve,
        "top_items": top_items,
    }


def build_concentration(connection: duckdb.DuckDBPyConnection, context: DatasetContext, filters: Filters) -> dict[str, Any]:
    revenue_available, revenue_reason = context.capability("revenue")
    if not revenue_available:
        return {"available": False, "reason": revenue_reason}
    payload: dict[str, Any] = {"available": True, "currency": context.currency}
    if context.capability("products")[0] and context.revenue_basis in LINE_BASES:
        rows = scoped_query(
            connection,
            context,
            filters,
            ("revenue",),
            f"SELECT COALESCE(CAST(product_key AS VARCHAR), '{NOT_SPECIFIED}') AS label, SUM(net_value) AS revenue FROM scoped WHERE contributes GROUP BY 1 ORDER BY 1",
        )
        values = np.array([number(item["revenue"]) for item in rows], dtype=float)
        payload["products"] = pareto_summary(values, [str(item["label"]) for item in rows], "products")
    else:
        payload["products"] = {"available": False, "reason": ORDER_TOTAL_REASON if context.capability("products")[0] else context.capability("products")[1]}
    if context.capability("customers")[0]:
        rows = scoped_query(
            connection,
            context,
            filters,
            ("revenue", "customer"),
            f"SELECT customer_id, {revenue_expression(context)} AS revenue FROM scoped GROUP BY 1 HAVING COUNT(*) FILTER (WHERE contributes) > 0 ORDER BY 1",
        )
        values = np.array([number(item["revenue"]) for item in rows], dtype=float)
        payload["customers"] = pareto_summary(values, None, "customers")
    else:
        payload["customers"] = {"available": False, "reason": context.capability("customers")[1]}
    payload["note"] = "Items are ranked by net revenue; items with zero or negative net revenue (for example fully returned) are left out of the curve and counted separately."
    return payload


def build_performance(connection: duckdb.DuckDBPyConnection, context: DatasetContext, filters: Filters) -> dict[str, Any]:
    return {
        "currency": context.currency,
        "orders_label": context.orders_label,
        "bridge": build_bridge(connection, context, filters),
        "profitability": build_profitability(connection, context, filters),
        "returns": build_returns(connection, context, filters),
        "discounts": build_discounts(connection, context, filters),
        "concentration": build_concentration(connection, context, filters),
        "filters": filters.to_dict(),
    }
