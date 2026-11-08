import datetime as dt
from typing import Any

import duckdb
import pandas as pd

from mieru.metrics.definitions import as_float
from mieru.metrics.upload import (
    UPLOAD_METRICS_BY_ID,
    DatasetContext,
    Filters,
    classified_cte,
    compute_metric,
    order_scope,
    orders_expression,
    revenue_expression,
)

DASHBOARD_KPIS: tuple[str, ...] = ("net_revenue", "orders", "customers", "units", "aov", "gross_profit", "returns_value", "discounts_value")
BREAKDOWN_LIMIT: int = 12
FILTER_OPTION_LIMIT: int = 60
NOT_SPECIFIED: str = "(not specified)"
BREAKDOWN_DIMENSIONS: dict[str, tuple[str, str]] = {
    "products": ("product_key", "products"),
    "categories": ("category", "categories"),
    "regions": ("region_dimension", "regions"),
    "channels": ("channel", "channels"),
}


def region_column(role_columns: dict[str, str]) -> str:
    for column in ("region", "country", "city"):
        if column in role_columns:
            return column
    return "region"


def choose_granularity(start: dt.date, end: dt.date) -> str:
    span = (end - start).days
    if span <= 62:
        return "day"
    if span <= 370:
        return "week"
    return "month"


def period_end(period_start: dt.date, granularity: str) -> dt.date:
    if granularity == "day":
        return period_start
    if granularity == "week":
        return period_start + dt.timedelta(days=6)
    next_month = (period_start.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    return next_month - dt.timedelta(days=1)


def percent_change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous == 0:
        return None
    return (current - previous) / abs(previous)


def next_period(period_start: dt.date, granularity: str) -> dt.date:
    if granularity == "day":
        return period_start + dt.timedelta(days=1)
    if granularity == "week":
        return period_start + dt.timedelta(days=7)
    return (period_start.replace(day=28) + dt.timedelta(days=4)).replace(day=1)


def period_floor(value: dt.date, granularity: str) -> dt.date:
    if granularity == "day":
        return value
    if granularity == "week":
        return value - dt.timedelta(days=value.weekday())
    return value.replace(day=1)


def as_date(value: Any) -> dt.date:
    return value.date() if isinstance(value, (pd.Timestamp, dt.datetime)) else value


def grouped_measures(
    connection: duckdb.DuckDBPyConnection, context: DatasetContext, filters: Filters, scopes: tuple[str, ...], group_sql: str, measures_sql: str
) -> dict[Any, dict[str, Any]]:
    cte_sql, parameters, _reasons = classified_cte(scopes, context, filters)
    cursor = connection.execute(
        f"""WITH {cte_sql.strip()}
SELECT {group_sql} AS group_key, {measures_sql}
FROM scoped
WHERE contributes
GROUP BY 1""",
        parameters,
    )
    names = [column[0] for column in cursor.description]
    return {row[0]: dict(zip(names[1:], row[1:])) for row in cursor.fetchall()}


def build_trend(connection: duckdb.DuckDBPyConnection, context: DatasetContext, filters: Filters) -> dict[str, Any]:
    trend_available, trend_reason = context.capability("trend")
    if not trend_available:
        return {"available": False, "reason": trend_reason}
    revenue_available, _ = context.capability("revenue")
    date_scopes = ("date",)
    cte_sql, parameters, _reasons = classified_cte(date_scopes, context, filters)
    bounds = connection.execute(
        f"WITH {cte_sql.strip()} SELECT MIN(CAST(order_ts AS DATE)), MAX(CAST(order_ts AS DATE)) FROM scoped WHERE contributes",
        parameters,
    ).fetchone()
    if bounds is None or bounds[0] is None:
        return {"available": False, "reason": "No contributing rows have a valid date for the current filters."}
    first_date, last_date = bounds
    granularity = choose_granularity(first_date, last_date)
    period_sql = f"CAST(date_trunc('{granularity}', order_ts) AS DATE)"
    order_measures = grouped_measures(
        connection,
        context,
        filters,
        date_scopes + order_scope(context),
        period_sql,
        f"{orders_expression(context)} AS orders, COUNT(*) AS contributing_rows",
    )
    revenue_measures = (
        grouped_measures(connection, context, filters, ("revenue",) + date_scopes, period_sql, f"{revenue_expression(context)} AS revenue")
        if revenue_available
        else {}
    )
    orders_by_period = {as_date(key): value for key, value in order_measures.items()}
    revenue_by_period = {as_date(key): value for key, value in revenue_measures.items()}
    points: list[dict[str, Any]] = []
    start = period_floor(first_date, granularity)
    while start <= last_date:
        end = period_end(start, granularity)
        is_partial = start < first_date or end > last_date if granularity != "day" else False
        order_row = orders_by_period.get(start, {})
        revenue_row = revenue_by_period.get(start, {})
        points.append(
            {
                "period": start.isoformat(),
                "period_end": end.isoformat(),
                "revenue": (as_float(revenue_row.get("revenue")) or 0.0) if revenue_available else None,
                "orders": int(order_row.get("orders") or 0),
                "contributing_rows": int(order_row.get("contributing_rows") or 0),
                "is_partial": bool(is_partial),
            }
        )
        start = next_period(start, granularity)
    complete = [point for point in points if not point["is_partial"]]
    comparison: dict[str, Any] = {"available": False, "reason": "Fewer than two complete periods are available."}
    if len(complete) >= 2:
        current, previous = complete[-1], complete[-2]
        comparison = {
            "available": True,
            "current_period": current["period"],
            "previous_period": previous["period"],
            "revenue_change": percent_change(current["revenue"], previous["revenue"]),
            "orders_change": percent_change(float(current["orders"]), float(previous["orders"])),
            "note": "Compares the last two complete periods; partial periods are excluded and periods without sales count as zero.",
        }
    return {
        "available": True,
        "granularity": granularity,
        "first_date": first_date.isoformat(),
        "last_date": last_date.isoformat(),
        "points": points,
        "comparison": comparison,
        "revenue_available": revenue_available,
    }


def build_breakdown(connection: duckdb.DuckDBPyConnection, context: DatasetContext, filters: Filters, key: str) -> dict[str, Any]:
    capability_name = BREAKDOWN_DIMENSIONS[key][1]
    available, reason = context.capability(capability_name)
    if not available:
        return {"available": False, "reason": reason}
    dimension = BREAKDOWN_DIMENSIONS[key][0]
    if dimension == "region_dimension":
        dimension = context.region_column
    revenue_available, _ = context.capability("revenue")
    line_revenue = revenue_available and context.revenue_basis != "order_total"
    group_sql = f"COALESCE({dimension}, '{NOT_SPECIFIED}')"
    order_measures = grouped_measures(connection, context, filters, order_scope(context), group_sql, f"{orders_expression(context)} AS orders, COUNT(*) AS rows")
    revenue_measures = grouped_measures(connection, context, filters, ("revenue",), group_sql, "SUM(net_value) AS revenue, COUNT(*) AS rows") if line_revenue else {}
    unit_measures = (
        grouped_measures(connection, context, filters, ("quantity",), group_sql, "SUM(quantity) FILTER (WHERE NOT is_return) AS units")
        if context.capability("units")[0]
        else {}
    )
    labels = set(order_measures) | set(revenue_measures) | set(unit_measures)
    records = []
    for label in labels:
        revenue_row = revenue_measures.get(label, {})
        order_row = order_measures.get(label, {})
        records.append(
            {
                "label": str(label),
                "revenue": as_float(revenue_row.get("revenue")) if line_revenue else None,
                "orders": int(order_row.get("orders") or 0),
                "units": as_float(unit_measures.get(label, {}).get("units")) if unit_measures else None,
                "rows": int((revenue_row if line_revenue else order_row).get("rows") or 0),
            }
        )
    records.sort(key=lambda record: (-(record["revenue"] if record["revenue"] is not None else float("-inf")), -record["orders"], record["label"]))
    total_revenue = sum(record["revenue"] or 0.0 for record in records) if line_revenue and records else None
    rows = [{**record, "revenue_share": (record["revenue"] or 0.0) / total_revenue if total_revenue else None} for record in records]
    top = rows[:BREAKDOWN_LIMIT]
    rest = rows[BREAKDOWN_LIMIT:]
    others = None
    if rest:
        others = {
            "label": f"Other ({len(rest)})",
            "revenue": sum(item["revenue"] or 0.0 for item in rest) if line_revenue else None,
            "revenue_share": sum(item["revenue_share"] or 0.0 for item in rest) if total_revenue else None,
            "rows": sum(item["rows"] for item in rest),
            "groups": len(rest),
        }
    note = None
    if revenue_available and not line_revenue:
        note = "Revenue is recorded as order totals, so it is not split by this dimension; order counts are shown instead."
    if key in {"products", "categories"} and context.grain != "transaction":
        note = (note + " " if note else "") + "Order counts are not additive across groups (one order can contain several)."
    return {
        "available": True,
        "dimension": dimension,
        "column": context.role_columns.get(dimension if dimension != "product_key" else ("product_name" if "product_name" in context.role_columns else "product_id")),
        "rows": top,
        "others": others,
        "total_groups": len(rows),
        "revenue_total": total_revenue,
        "revenue_shown": line_revenue,
        "note": note,
    }


def filter_options(connection: duckdb.DuckDBPyConnection, context: DatasetContext) -> dict[str, Any]:
    options: dict[str, Any] = {}
    for key, column in (("categories", "category"), ("regions", context.region_column), ("channels", "channel")):
        available, _ = context.capability(key)
        if not available:
            continue
        values = connection.execute(
            f"SELECT {column} AS value, COUNT(*) AS rows FROM canon_lines WHERE {column} IS NOT NULL AND NOT is_blank "
            f"GROUP BY 1 ORDER BY rows DESC, value LIMIT {FILTER_OPTION_LIMIT}"
        ).fetchall()
        options[key] = [value for value, _rows in values]
    if context.capability("trend")[0]:
        bounds = connection.execute("SELECT MIN(CAST(order_ts AS DATE)), MAX(CAST(order_ts AS DATE)) FROM canon_lines WHERE NOT date_invalid").fetchone()
        if bounds and bounds[0]:
            options["date_min"] = bounds[0].isoformat()
            options["date_max"] = bounds[1].isoformat()
    return options


def build_dashboard(connection: duckdb.DuckDBPyConnection, context: DatasetContext, filters: Filters) -> dict[str, Any]:
    kpis = []
    for metric_id in DASHBOARD_KPIS:
        explanation = compute_metric(connection, UPLOAD_METRICS_BY_ID[metric_id], context, filters)
        kpis.append(
            {
                "metric_id": metric_id,
                "label": explanation.definition.label,
                "value": explanation.value,
                "unit": explanation.definition.unit,
                "currency": explanation.currency,
                "status": explanation.status,
                "unavailable_reason": explanation.unavailable_reason,
                "context": None,
            }
        )
    return {
        "kpis": kpis,
        "trend": build_trend(connection, context, filters),
        "breakdowns": {key: build_breakdown(connection, context, filters, key) for key in BREAKDOWN_DIMENSIONS},
        "filters": {"applied": filters.to_dict(), "options": filter_options(connection, context)},
    }
