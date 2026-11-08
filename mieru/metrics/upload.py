import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from typing import Any

import duckdb

from mieru.metrics.definitions import ExcludedRecords, MetricDefinition, MetricExplanation, RecordCounts, as_float

POLICY_DEFAULTS: dict[str, bool] = {
    "exclude_blank_rows": True,
    "exclude_reliable_duplicates": True,
    "exclude_possible_duplicates": False,
    "exclude_cancelled": True,
}
POLICY_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "exclude_blank_rows": {
        "label": "Exclude blank rows",
        "description": "Rows where every cell is empty carry no transaction and are excluded.",
    },
    "exclude_reliable_duplicates": {
        "label": "Exclude confirmed duplicates",
        "description": "Rows that repeat an earlier row's transaction identifier with identical content are excluded once.",
    },
    "exclude_possible_duplicates": {
        "label": "Exclude possible duplicates",
        "description": "Identical rows without a reliable transaction ID could be genuine repeat purchases, so they are kept unless you opt in.",
    },
    "exclude_cancelled": {
        "label": "Exclude cancelled orders",
        "description": "Rows whose status means cancelled / void are not sales and are excluded from sales metrics.",
    },
}
EXCLUSION_LABELS: dict[str, str] = {
    "blank_row": "Blank rows",
    "duplicate_reliable": "Confirmed duplicates (same transaction ID, identical content)",
    "duplicate_possible": "Possible duplicates (identical rows; excluded only if you opt in)",
    "cancelled": "Cancelled orders",
    "order_total_conflict": "Orders whose total differs between their lines",
    "invalid_amount": "Missing or unreadable amount",
    "invalid_date": "Missing or unreadable date",
    "invalid_quantity": "Missing or unreadable quantity",
    "missing_customer": "No customer identifier",
    "missing_order": "No order identifier",
    "missing_cost": "No cost recorded",
}
BASE_REASONS: tuple[str, ...] = ("blank_row", "duplicate_reliable", "duplicate_possible", "cancelled")
FLAG_LABELS: dict[str, str] = {
    "dup_possible": "Possible duplicates (kept)",
    "key_conflict": "Same ID, conflicting values (kept)",
    "negative_unverified": "Negative amounts with unverified meaning (kept as recorded)",
    "is_outlier": "Statistical outliers (kept, flagged only)",
    "is_ragged": "Malformed rows (wrong number of fields)",
    "text_normalized": "Text values normalised (trim / case)",
    "is_return": "Returns / credits (netted)",
}
LINE_BASES: frozenset[str] = frozenset({"line_amount", "quantity_x_unit_price", "unit_price_one_unit_per_row"})


@dataclass(frozen=True)
class Filters:
    start: dt.date | None = None
    end: dt.date | None = None
    categories: tuple[str, ...] = ()
    regions: tuple[str, ...] = ()
    channels: tuple[str, ...] = ()

    def is_empty(self) -> bool:
        return not (self.start or self.end or self.categories or self.regions or self.channels)

    def where(self, region_column: str) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        parameters: list[Any] = []
        if self.start:
            clauses.append("CAST(order_ts AS DATE) >= ?")
            parameters.append(self.start)
        if self.end:
            clauses.append("CAST(order_ts AS DATE) <= ?")
            parameters.append(self.end)
        if self.categories:
            clauses.append("list_contains(?, category)")
            parameters.append(list(self.categories))
        if self.regions:
            clauses.append(f"list_contains(?, {region_column})")
            parameters.append(list(self.regions))
        if self.channels:
            clauses.append("list_contains(?, channel)")
            parameters.append(list(self.channels))
        return (" AND ".join(clauses) if clauses else "TRUE"), parameters

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": self.start.isoformat() if self.start else None,
            "end": self.end.isoformat() if self.end else None,
            "categories": list(self.categories),
            "regions": list(self.regions),
            "channels": list(self.channels),
        }

    def cache_key(self) -> str:
        return hashlib.sha1(json.dumps(self.to_dict(), sort_keys=True).encode()).hexdigest()[:16]


@dataclass(frozen=True)
class DatasetContext:
    grain: str
    revenue_basis: str | None
    currency: str | None
    capabilities: dict[str, dict[str, Any]]
    role_columns: dict[str, str]
    policies: dict[str, bool]
    region_column: str = "region"

    def capability(self, name: str) -> tuple[bool, str | None]:
        entry = self.capabilities.get(name, {"available": False, "reason": "Not available."})
        return bool(entry.get("available")), entry.get("reason")

    def policy_parameters(self, policies: dict[str, bool] | None = None) -> list[bool]:
        active = {**POLICY_DEFAULTS, **(policies if policies is not None else self.policies)}
        return [active["exclude_blank_rows"], active["exclude_reliable_duplicates"], active["exclude_possible_duplicates"], active["exclude_cancelled"]]

    @property
    def orders_label(self) -> str:
        return "Transactions" if self.grain == "transaction" else "Orders"


@dataclass(frozen=True)
class UploadMetric:
    metric_id: str
    label: str
    description: str
    formula: str
    unit: str
    scopes: tuple[str, ...]
    requires: tuple[str, ...]
    assumptions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


def revenue_expression(context: DatasetContext) -> str:
    return "SUM(order_value_once) FILTER (WHERE contributes)" if context.revenue_basis == "order_total" else "SUM(net_value) FILTER (WHERE contributes)"


def orders_expression(context: DatasetContext) -> str:
    if context.grain == "transaction":
        return "COUNT(*) FILTER (WHERE contributes AND NOT is_return)"
    return "COUNT(DISTINCT order_id) FILTER (WHERE contributes AND NOT is_return)"


def order_scope(context: DatasetContext) -> tuple[str, ...]:
    return () if context.grain == "transaction" else ("order",)


UPLOAD_METRICS: tuple[UploadMetric, ...] = (
    UploadMetric(
        "net_revenue",
        "Net revenue",
        "Sales value after verified returns and (where recorded separately) discounts, excluding cancelled and invalid rows.",
        "Σ net line value over contributing rows (or Σ order total once per order)",
        "currency",
        ("revenue",),
        ("revenue",),
        limitations=("Shipping and tax columns, when present, are reported separately and not included in revenue.",),
    ),
    UploadMetric(
        "gross_sales",
        "Gross sales",
        "Sales value before returns, excluding cancelled and invalid rows.",
        "Σ line value over contributing non-return rows",
        "currency",
        ("revenue",),
        ("revenue", "line_revenue"),
    ),
    UploadMetric(
        "returns_value",
        "Returns & credits",
        "Value of rows identified as returns (return status, return flag or negative quantity), net of any discount on the returned line.",
        "−Σ net line value over contributing return rows",
        "currency",
        ("revenue",),
        ("revenue", "returns", "line_revenue"),
    ),
    UploadMetric(
        "discounts_value",
        "Discounts",
        "Discount amounts recorded on contributing sales rows.",
        "Σ discount amount over contributing non-return rows",
        "currency",
        ("revenue",),
        ("revenue", "discounts"),
    ),
    UploadMetric(
        "orders",
        "Orders",
        "Distinct orders with at least one contributing sales line (returns-only orders are not counted).",
        "COUNT(DISTINCT order_id) over contributing non-return rows",
        "count",
        (),
        ("orders",),
    ),
    UploadMetric(
        "customers",
        "Customers",
        "Distinct customer identifiers on contributing rows.",
        "COUNT(DISTINCT customer_id) over contributing rows",
        "count",
        ("customer",),
        ("customers",),
    ),
    UploadMetric(
        "units",
        "Units sold",
        "Total quantity on contributing sales rows.",
        "Σ quantity over contributing non-return rows",
        "count",
        ("quantity",),
        ("units",),
    ),
    UploadMetric(
        "aov",
        "Average order value",
        "Net revenue divided by the number of orders with valid amounts.",
        "Net revenue ÷ orders (same contributing rows)",
        "currency",
        ("revenue",),
        ("revenue",),
    ),
    UploadMetric(
        "gross_profit",
        "Gross profit",
        "Net revenue minus recorded cost, on rows that have both.",
        "Σ (net line value − cost) over contributing rows with cost",
        "currency",
        ("revenue", "cost"),
        ("revenue", "profit"),
    ),
    UploadMetric(
        "gross_margin",
        "Gross margin",
        "Gross profit as a share of net revenue on rows that have cost.",
        "Gross profit ÷ net revenue (rows with cost)",
        "ratio",
        ("revenue", "cost"),
        ("revenue", "profit"),
    ),
    UploadMetric(
        "return_rate",
        "Return rate",
        "Returns value as a share of sales after discounts (before returns).",
        "Returns & credits ÷ net sales before returns",
        "ratio",
        ("revenue",),
        ("revenue", "returns", "line_revenue"),
    ),
)
UPLOAD_METRICS_BY_ID: dict[str, UploadMetric] = {metric.metric_id: metric for metric in UPLOAD_METRICS}


def value_expression(metric: UploadMetric, context: DatasetContext) -> str:
    revenue = revenue_expression(context)
    orders = orders_expression(context)
    expressions = {
        "net_revenue": revenue,
        "gross_sales": "SUM(signed_value) FILTER (WHERE contributes AND NOT is_return)",
        "returns_value": "-SUM(net_value) FILTER (WHERE contributes AND is_return)",
        "discounts_value": "SUM(discount_value) FILTER (WHERE contributes AND NOT is_return)",
        "orders": orders,
        "customers": "COUNT(DISTINCT customer_id) FILTER (WHERE contributes)",
        "units": "SUM(quantity) FILTER (WHERE contributes AND NOT is_return)",
        "aov": f"({revenue}) / NULLIF({orders}, 0)",
        "gross_profit": "SUM(net_value - cost_value) FILTER (WHERE contributes)",
        "gross_margin": "SUM(net_value - cost_value) FILTER (WHERE contributes) / NULLIF(SUM(net_value) FILTER (WHERE contributes), 0)",
        "return_rate": "(-SUM(net_value) FILTER (WHERE contributes AND is_return)) / NULLIF(SUM(net_value) FILTER (WHERE contributes AND NOT is_return), 0)",
    }
    return expressions[metric.metric_id]


def scope_reasons(scopes: tuple[str, ...], context: DatasetContext) -> list[tuple[str, str]]:
    cases: list[tuple[str, str]] = []
    if "revenue" in scopes:
        if context.revenue_basis == "order_total":
            cases.append(("order_total_conflict", "order_total_conflict"))
        cases.append(("invalid_amount", "value_invalid"))
    if "date" in scopes:
        cases.append(("invalid_date", "date_invalid"))
    if "quantity" in scopes:
        cases.append(("invalid_quantity", "quantity_invalid"))
    if "customer" in scopes:
        cases.append(("missing_customer", "customer_id IS NULL"))
    if "order" in scopes:
        cases.append(("missing_order", "order_id IS NULL"))
    if "cost" in scopes:
        cases.append(("missing_cost", "cost_value IS NULL"))
    return cases


def classified_cte(scopes: tuple[str, ...], context: DatasetContext, filters: Filters, policies: dict[str, bool] | None = None) -> tuple[str, list[Any], list[str]]:
    extra = scope_reasons(scopes, context)
    case_lines = [
        "WHEN ? AND is_blank THEN 'blank_row'",
        "WHEN ? AND dup_reliable THEN 'duplicate_reliable'",
        "WHEN ? AND dup_possible THEN 'duplicate_possible'",
        "WHEN ? AND is_cancelled THEN 'cancelled'",
    ] + [f"WHEN {condition} THEN '{reason}'" for reason, condition in extra]
    where_sql, where_parameters = filters.where(context.region_column)
    sql = f"""
classified AS (
    SELECT *,
        CASE
            {chr(10).join('            ' + line for line in case_lines).strip()}
            ELSE NULL
        END AS exclusion_reason
    FROM canon_lines
    WHERE {where_sql}
),
ranked AS (
    SELECT *,
        exclusion_reason IS NULL AS contributes,
        ROW_NUMBER() OVER (PARTITION BY order_id, exclusion_reason IS NULL ORDER BY _row_id) AS order_line_rank
    FROM classified
),
scoped AS (
    SELECT *,
        CASE
            WHEN NOT contributes THEN NULL
            WHEN order_id IS NULL THEN order_total
            WHEN order_line_rank = 1 THEN order_total
            ELSE NULL
        END AS order_value_once
    FROM ranked
)"""
    reasons = list(BASE_REASONS) + [reason for reason, _condition in extra]
    return sql, context.policy_parameters(policies) + where_parameters, reasons


def render_sql_for_display(sql: str, parameters: list[Any]) -> str:
    rendered = sql
    for parameter in parameters:
        if isinstance(parameter, bool):
            literal = "TRUE" if parameter else "FALSE"
        elif isinstance(parameter, (dt.date, dt.datetime)):
            literal = f"DATE '{parameter.isoformat()}'"
        elif isinstance(parameter, list):
            literal = "[" + ", ".join("'" + str(item).replace("'", "''") + "'" for item in parameter) + "]"
        else:
            literal = repr(parameter)
        rendered = rendered.replace("?", literal, 1)
    return "\n".join(line.rstrip() for line in rendered.strip().splitlines() if line.strip())


def metric_availability(metric: UploadMetric, context: DatasetContext) -> tuple[bool, str | None]:
    for requirement in metric.requires:
        if requirement == "line_revenue":
            if context.revenue_basis not in LINE_BASES:
                return False, "Revenue is recorded per order total, so this line-level measure cannot be separated without allocating order values."
            continue
        available, reason = context.capability(requirement)
        if not available:
            return False, reason
    return True, None


def metric_definition(metric: UploadMetric, context: DatasetContext) -> MetricDefinition:
    source_columns = []
    for role in ("line_amount", "order_total", "quantity", "unit_price", "discount", "unit_cost", "line_cost", "order_id", "customer_id", "order_date", "status"):
        if role in context.role_columns:
            source_columns.append(f"{context.role_columns[role]} → {role}")
    label = metric.label if metric.metric_id != "orders" else context.orders_label
    exclusions = [EXCLUSION_LABELS[reason] for reason in BASE_REASONS] + [EXCLUSION_LABELS[reason] for reason, _ in scope_reasons(metric.scopes + (order_scope(context) if metric.metric_id in {"orders", "aov"} else ()), context)]
    return MetricDefinition(
        metric_id=f"upload.{metric.metric_id}",
        label=label,
        description=metric.description,
        formula=metric.formula,
        unit=metric.unit,
        grain="source row",
        source="upload",
        source_columns=tuple(source_columns),
        transformations=("Values parsed from text with the detected number/date conventions; source file unchanged.",),
        exclusions=tuple(dict.fromkeys(exclusions)),
        assumptions=metric.assumptions,
        limitations=metric.limitations,
    )


def effective_scopes(metric: UploadMetric, context: DatasetContext) -> tuple[str, ...]:
    if metric.metric_id in {"orders", "aov"}:
        return metric.scopes + order_scope(context)
    return metric.scopes


def compute_metric(
    connection: duckdb.DuckDBPyConnection,
    metric: UploadMetric,
    context: DatasetContext,
    filters: Filters,
    policies: dict[str, bool] | None = None,
) -> MetricExplanation:
    definition = metric_definition(metric, context)
    currency = context.currency if metric.unit == "currency" else None
    available, reason = metric_availability(metric, context)
    if not available:
        return MetricExplanation(definition=definition, status="unavailable", value=None, sql="", record_counts=None, unavailable_reason=reason, currency=currency)
    scopes = effective_scopes(metric, context)
    cte_sql, parameters, reasons = classified_cte(scopes, context, filters, policies)
    reason_columns = ",\n    ".join(f"COUNT(*) FILTER (WHERE exclusion_reason = '{reason}') AS excluded_{reason}" for reason in reasons)
    flag_columns = ",\n    ".join(f"COUNT(*) FILTER (WHERE contributes AND {flag}) AS flag_{flag}" for flag in FLAG_LABELS)
    sql = f"""WITH {cte_sql.strip()}
SELECT
    {value_expression(metric, context)} AS value,
    COUNT(*) AS input_records,
    COUNT(*) FILTER (WHERE contributes) AS contributing_records,
    {reason_columns},
    {flag_columns},
    COUNT(DISTINCT order_id) AS context_input_orders,
    COUNT(DISTINCT order_id) FILTER (WHERE contributes) AS context_contributing_orders,
    COUNT(*) FILTER (WHERE contributes AND is_return) AS context_return_rows
FROM scoped"""
    cursor = connection.execute(sql, parameters)
    column_names = [column[0] for column in cursor.description]
    row = dict(zip(column_names, cursor.fetchone()))
    total_rows = connection.execute("SELECT COUNT(*) FROM canon_lines").fetchone()[0]
    excluded = [
        ExcludedRecords(reason=reason, label=EXCLUSION_LABELS[reason], records=int(row[f"excluded_{reason}"]))
        for reason in reasons
        if int(row[f"excluded_{reason}"]) > 0
    ]
    overlapping = [
        ExcludedRecords(reason=flag, label=label, records=int(row[f"flag_{flag}"]))
        for flag, label in FLAG_LABELS.items()
        if int(row[f"flag_{flag}"]) > 0
    ]
    counts = RecordCounts(
        grain="source row",
        input_records=int(row["input_records"]),
        contributing_records=int(row["contributing_records"]),
        excluded=excluded,
        overlapping_flags=overlapping,
    )
    context_payload: dict[str, Any] = {
        "rows_in_file": int(total_rows),
        "rows_outside_active_filters": int(total_rows) - int(row["input_records"]),
        "return_rows_netted": int(row["context_return_rows"]),
    }
    if context.grain != "transaction":
        context_payload["orders_in_scope"] = int(row["context_input_orders"])
        context_payload["orders_contributing"] = int(row["context_contributing_orders"])
    active_policies = {**POLICY_DEFAULTS, **(policies if policies is not None else context.policies)}
    return MetricExplanation(
        definition=definition,
        status="ok",
        value=as_float(row["value"]),
        sql=render_sql_for_display(sql, parameters),
        record_counts=counts,
        lineage=[
            "Uploaded file (kept unchanged) → src_rows (all text, one row per source row)",
            "Detected column roles + parsing conventions → canon_lines (typed canonical lines + quality flags)",
            "Active cleaning policies → one primary exclusion reason per row → contributing rows → metric",
        ],
        currency=currency,
        context={**context_payload, "active_policies": active_policies, "filters": filters.to_dict()},
    )


def metric_value(connection: duckdb.DuckDBPyConnection, metric_id: str, context: DatasetContext, filters: Filters, policies: dict[str, bool] | None = None) -> float | None:
    return compute_metric(connection, UPLOAD_METRICS_BY_ID[metric_id], context, filters, policies).value
