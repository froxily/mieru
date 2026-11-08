from typing import Any

import duckdb

from mieru.metrics.upload import (
    POLICY_DEFAULTS,
    POLICY_DESCRIPTIONS,
    UPLOAD_METRICS_BY_ID,
    DatasetContext,
    Filters,
    compute_metric,
)
from mieru.schema.aliases import ROLE_LABELS

IMPACT_METRICS: tuple[str, ...] = ("net_revenue", "orders", "customers", "units", "aov")
ALL_POLICIES_OFF: dict[str, bool] = {key: False for key in POLICY_DEFAULTS}

ISSUE_DEFINITIONS: tuple[dict[str, str], ...] = (
    {"code": "is_blank", "label": "Blank rows", "treatment": "excluded", "policy": "exclude_blank_rows", "explanation": "Rows with no values at all."},
    {"code": "is_ragged", "label": "Malformed rows", "treatment": "flagged", "explanation": "Rows with more or fewer fields than the header; extra values were dropped and missing ones left empty."},
    {"code": "dup_reliable", "label": "Confirmed duplicates", "treatment": "excluded", "policy": "exclude_reliable_duplicates", "explanation": "Same transaction identifier and identical content as an earlier row."},
    {"code": "dup_possible", "label": "Possible duplicates", "treatment": "kept", "policy": "exclude_possible_duplicates", "explanation": "Identical rows without a reliable transaction ID. They may be genuine repeat purchases, so they are kept by default."},
    {"code": "key_conflict", "label": "Conflicting rows for the same ID", "treatment": "kept", "explanation": "The same transaction identifier appears with different values; kept and flagged for review."},
    {"code": "is_cancelled", "label": "Cancelled orders", "treatment": "excluded", "policy": "exclude_cancelled", "explanation": "Status indicates cancellation, so the row is not a sale."},
    {"code": "value_invalid", "label": "Missing or unreadable amounts", "treatment": "excluded from revenue", "explanation": "The revenue value could not be read; the row still counts for order and customer counts."},
    {"code": "date_invalid", "label": "Missing or unreadable dates", "treatment": "excluded from trends", "explanation": "The row counts in totals but cannot be placed on the timeline."},
    {"code": "quantity_invalid", "label": "Missing or unreadable quantities", "treatment": "excluded from units", "explanation": "Units sold ignore these rows."},
    {"code": "order_total_conflict", "label": "Inconsistent order totals", "treatment": "excluded from revenue", "explanation": "An order's total differs between its lines, so it is not summed."},
    {"code": "negative_unverified", "label": "Negative amounts (meaning unverified)", "treatment": "kept as recorded", "explanation": "Negative values without a return status or negative quantity; kept as recorded and flagged."},
    {"code": "is_return", "label": "Returns / credits", "treatment": "netted", "explanation": "Identified by return status, a return flag or a negative quantity; subtracted from net revenue."},
    {"code": "is_outlier", "label": "Statistical outliers", "treatment": "flagged only", "explanation": "Values far from the typical range (robust z-score > 8); never removed automatically."},
    {"code": "text_normalized", "label": "Text normalised", "treatment": "normalised", "explanation": "Whitespace trimmed and capitalisation variants unified (e.g. 'electronics' → 'Electronics')."},
)


def issue_severity(code: str, share: float) -> str:
    if code in {"value_invalid", "order_total_conflict", "key_conflict"} and share >= 0.05:
        return "critical"
    if code in {"is_ragged", "dup_reliable", "dup_possible", "value_invalid", "date_invalid", "negative_unverified", "key_conflict", "order_total_conflict", "quantity_invalid"}:
        return "warning"
    return "info"


def flag_counts(connection: duckdb.DuckDBPyConnection) -> tuple[int, dict[str, int]]:
    codes = [definition["code"] for definition in ISSUE_DEFINITIONS]
    select = ", ".join(f"COUNT(*) FILTER (WHERE {code}{' AND NOT is_blank' if code not in {'is_blank'} else ''}) AS {code}" for code in codes)
    row = connection.execute(f"SELECT COUNT(*) AS total, {select} FROM canon_lines").fetchone()
    return int(row[0]), {code: int(value) for code, value in zip(codes, row[1:])}


def headline_metric_id(context: DatasetContext) -> str:
    return "net_revenue" if context.capability("revenue")[0] else "orders"


def build_quality(
    connection: duckdb.DuckDBPyConnection,
    context: DatasetContext,
    source: dict[str, Any],
    profiles: list[dict[str, Any]],
    assignments: dict[str, Any],
    audit: list[dict[str, Any]],
    filters: Filters | None = None,
) -> dict[str, Any]:
    filters = filters or Filters()
    total_rows, counts = flag_counts(connection)
    issues = []
    for definition in ISSUE_DEFINITIONS:
        rows = counts[definition["code"]]
        if rows == 0:
            continue
        treatment = definition["treatment"]
        policy = definition.get("policy")
        if policy is not None:
            treatment = "excluded" if context.policies.get(policy, POLICY_DEFAULTS[policy]) else "kept"
        share = rows / total_rows if total_rows else 0.0
        issues.append(
            {
                "code": definition["code"],
                "label": definition["label"],
                "rows": rows,
                "share": share,
                "severity": issue_severity(definition["code"], share),
                "treatment": treatment,
                "policy": policy,
                "explanation": definition["explanation"],
            }
        )
    headline = compute_metric(connection, UPLOAD_METRICS_BY_ID[headline_metric_id(context)], context, filters)
    impact = []
    for metric_id in IMPACT_METRICS:
        metric = UPLOAD_METRICS_BY_ID[metric_id]
        cleaned = compute_metric(connection, metric, context, filters)
        if cleaned.status != "ok":
            continue
        raw = compute_metric(connection, metric, context, filters, ALL_POLICIES_OFF)
        delta = None if cleaned.value is None or raw.value is None else cleaned.value - raw.value
        impact.append(
            {
                "metric_id": metric_id,
                "label": cleaned.definition.label,
                "unit": cleaned.definition.unit,
                "currency": cleaned.currency,
                "without_policies": raw.value,
                "with_policies": cleaned.value,
                "delta": delta,
                "delta_share": (delta / raw.value) if (delta is not None and raw.value) else None,
            }
        )
    headline_metric = UPLOAD_METRICS_BY_ID[headline_metric_id(context)]
    policies = []
    for key, default in POLICY_DEFAULTS.items():
        enabled = context.policies.get(key, default)
        toggled = {**POLICY_DEFAULTS, **context.policies, key: not enabled}
        toggled_value = compute_metric(connection, headline_metric, context, filters, toggled).value
        policies.append(
            {
                "key": key,
                "label": POLICY_DESCRIPTIONS[key]["label"],
                "description": POLICY_DESCRIPTIONS[key]["description"],
                "enabled": enabled,
                "default": default,
                "impact_metric": headline_metric_id(context),
                "value_now": headline.value,
                "value_if_toggled": toggled_value,
                "delta_if_toggled": None if toggled_value is None or headline.value is None else toggled_value - headline.value,
            }
        )
    role_by_column = {entry["column_name"]: role for role, entry in assignments.items()}
    columns = [
        {
            "name": profile["name"],
            "role": role_by_column.get(profile["name"]),
            "role_label": ROLE_LABELS.get(role_by_column.get(profile["name"], ""), None),
            "non_null_share": profile["non_null"] / max(1, profile["non_null"] + profile["null_count"]),
            "distinct": profile["distinct"],
            "numeric_rate": profile["numeric_rate"],
            "date_rate": profile["date_rate"],
            "date_formats": profile["date_formats"],
            "numeric_convention": profile["numeric_convention"],
            "currency_codes": profile["currency_codes"],
            "sample_values": profile["sample_values"][:3],
        }
        for profile in profiles
    ]
    return {
        "source": source,
        "summary": {
            "rows_in_file": total_rows,
            "headline_metric": headline_metric_id(context),
            "record_counts": headline.record_counts.to_dict() if headline.record_counts else None,
        },
        "issues": issues,
        "impact": impact,
        "policies": policies,
        "columns": columns,
        "audit": audit,
    }
