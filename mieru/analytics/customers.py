from typing import Any

import duckdb
import numpy as np
import pandas as pd

from mieru.metrics.upload import UPLOAD_METRICS_BY_ID, DatasetContext, Filters, classified_cte, compute_metric

MIN_CUSTOMERS: int = 50
MIN_SPAN_DAYS: int = 60
REPEAT_HORIZON_DAYS: int = 90
MAX_COHORT_PERIODS: int = 12
SCORE_BINS: int = 5
SEGMENT_ORDER: tuple[str, ...] = (
    "Champions",
    "Loyal customers",
    "Potential loyalists",
    "New customers",
    "Needs attention",
    "At risk",
    "Hibernating",
)
SEGMENT_GUIDANCE: dict[str, str] = {
    "Champions": "Bought recently, buy often and spend the most: reward and ask for referrals.",
    "Loyal customers": "Buy often: offer loyalty benefits and early access.",
    "Potential loyalists": "Recent customers with a few orders: nudge towards a membership or subscription.",
    "New customers": "First purchase was recent: onboard well so a second order follows.",
    "Needs attention": "Middling recency and frequency: re-engage with personalised offers.",
    "At risk": "Used to buy often but not recently: win-back campaign before they lapse.",
    "Hibernating": "Low recency and frequency: low-cost reactivation only.",
}


def percentile_scores(values: pd.Series, higher_is_better: bool) -> pd.Series:
    ranks = values.rank(method="average", pct=True)
    if not higher_is_better:
        ranks = 1 - ranks + (1 / len(values))
    return np.clip(np.ceil(ranks * SCORE_BINS), 1, SCORE_BINS).astype(int)


def frequency_scores(frequency: pd.Series) -> pd.Series:
    scores = pd.Series(1, index=frequency.index, dtype=int)
    repeaters = frequency[frequency >= 2]
    if not repeaters.empty:
        ranks = repeaters.rank(method="average", pct=True)
        scores.loc[repeaters.index] = np.clip(np.ceil(ranks * (SCORE_BINS - 1)), 1, SCORE_BINS - 1).astype(int) + 1
    return scores


def assign_segment(recency_score: int, frequency_score: int) -> str:
    if recency_score >= 4 and frequency_score >= 4:
        return "Champions"
    if frequency_score >= 4:
        return "Loyal customers" if recency_score >= 3 else "At risk"
    if recency_score == 5 and frequency_score <= 1:
        return "New customers"
    if recency_score >= 4:
        return "Potential loyalists"
    if recency_score <= 2 and frequency_score >= 3:
        return "At risk"
    if recency_score <= 2:
        return "Hibernating"
    return "Needs attention"


def customer_intelligence(orders: pd.DataFrame, currency: str | None, orders_label: str = "orders") -> dict[str, Any]:
    clean = orders.dropna(subset=["customer_id", "order_date"]).copy()
    clean["order_date"] = pd.to_datetime(clean["order_date"]).dt.normalize()
    if "is_sale" not in clean.columns:
        clean["is_sale"] = True
    clean["is_sale"] = clean["is_sale"].astype(bool)
    if clean.empty or not clean["is_sale"].any():
        return {"available": False, "reason": "No orders have both a customer identifier and a readable date."}
    span_days = int((clean["order_date"].max() - clean["order_date"].min()).days)
    sales = clean[clean["is_sale"]]
    customers = sales.groupby("customer_id").agg(
        first_order=("order_date", "min"),
        last_order=("order_date", "max"),
        frequency=("order_key", "nunique"),
    )
    customers["monetary"] = clean.groupby("customer_id")["revenue"].sum().reindex(customers.index).fillna(0.0)
    if len(customers) < MIN_CUSTOMERS:
        return {"available": False, "reason": f"Customer analytics needs at least {MIN_CUSTOMERS} identified customers; this data has {len(customers)}."}
    if span_days < MIN_SPAN_DAYS:
        return {"available": False, "reason": f"Customer analytics needs at least {MIN_SPAN_DAYS} days of history; this data spans {span_days}."}
    reference = clean["order_date"].max() + pd.Timedelta(days=1)
    customers["recency_days"] = (reference - customers["last_order"]).dt.days
    customers["r_score"] = percentile_scores(customers["recency_days"], higher_is_better=False)
    customers["f_score"] = frequency_scores(customers["frequency"])
    customers["m_score"] = percentile_scores(customers["monetary"].fillna(0.0), higher_is_better=True)
    customers["segment"] = [assign_segment(int(r), int(f)) for r, f in zip(customers["r_score"], customers["f_score"])]
    total_revenue = float(customers["monetary"].sum())
    segments = []
    for name in SEGMENT_ORDER:
        group = customers[customers["segment"] == name]
        if group.empty:
            continue
        segments.append(
            {
                "segment": name,
                "customers": int(len(group)),
                "customer_share": len(group) / len(customers),
                "revenue": float(group["monetary"].sum()),
                "revenue_share": float(group["monetary"].sum()) / total_revenue if total_revenue else None,
                "mean_recency_days": float(group["recency_days"].mean()),
                "mean_frequency": float(group["frequency"].mean()),
                "mean_monetary": float(group["monetary"].mean()),
                "guidance": SEGMENT_GUIDANCE[name],
            }
        )
    data_end = clean["order_date"].max()
    eligible = customers[customers["first_order"] <= data_end - pd.Timedelta(days=REPEAT_HORIZON_DAYS)]
    repeat_within = None
    if len(eligible) >= MIN_CUSTOMERS:
        orders_with_first = sales.merge(customers[["first_order"]], left_on="customer_id", right_index=True)
        later = orders_with_first[
            (orders_with_first["order_date"] > orders_with_first["first_order"])
            & (orders_with_first["order_date"] <= orders_with_first["first_order"] + pd.Timedelta(days=REPEAT_HORIZON_DAYS))
        ]
        repeaters = set(later["customer_id"]) & set(eligible.index)
        repeat_within = {
            "horizon_days": REPEAT_HORIZON_DAYS,
            "eligible_customers": int(len(eligible)),
            "repeat_customers": int(len(repeaters)),
            "rate": len(repeaters) / len(eligible),
            "note": (
                f"Only customers whose first order was at least {REPEAT_HORIZON_DAYS} days before the data ends are counted, so every customer had the same chance to return. "
                "A repeat is an order on a later calendar day than the first purchase; extra orders on the first day count as the same visit, so split baskets are not mistaken for loyalty."
            ),
        }
    activity = sales.copy()
    activity["cohort"] = activity["customer_id"].map(customers["first_order"]).dt.to_period("M")
    activity["activity"] = activity["order_date"].dt.to_period("M")
    activity["period_number"] = (activity["activity"] - activity["cohort"]).apply(lambda offset: offset.n)
    data_end_month = data_end.to_period("M")
    last_complete_month = data_end_month if data_end == data_end_month.end_time.normalize() else data_end_month - 1
    cohort_sizes = activity.groupby("cohort")["customer_id"].nunique()
    active = activity[activity["period_number"] <= MAX_COHORT_PERIODS].groupby(["cohort", "period_number"])["customer_id"].nunique()
    cohort_rows = []
    for cohort, size in cohort_sizes.sort_index().items():
        observable = min(MAX_COHORT_PERIODS, max(0, (last_complete_month - cohort).n))
        values = []
        for period in range(0, MAX_COHORT_PERIODS + 1):
            values.append(None if period > observable else 100.0 * int(active.get((cohort, period), 0)) / int(size))
        cohort_rows.append({"cohort": str(cohort), "size": int(size), "retention_pct": values})
    top_customers = customers.sort_values("monetary", ascending=False).head(10)
    return {
        "available": True,
        "currency": currency,
        "customers": int(len(customers)),
        "revenue_total": total_revenue,
        "reference_date": (reference - pd.Timedelta(days=1)).date().isoformat(),
        "orders_label": orders_label,
        "segments": segments,
        "score_method": f"Recency and monetary value are scored 1–{SCORE_BINS} by percentile rank (ties share a score); frequency is 1 for single-purchase customers and 2–{SCORE_BINS} by percentile among repeat customers; segments follow the standard RFM grid on R and F.",
        "repeat_within_horizon": repeat_within,
        "cohorts": {"rows": cohort_rows, "periods": list(range(0, MAX_COHORT_PERIODS + 1)), "note": "Blank cells are not yet fully observable (right-censored); a final month that the data does not cover to its last day counts as incomplete."},
        "top_customers": [
            {
                "customer": f"Customer …{str(customer_id)[-4:]}",
                "orders": int(row["frequency"]),
                "revenue": float(row["monetary"]),
                "recency_days": int(row["recency_days"]),
                "segment": row["segment"],
            }
            for customer_id, row in top_customers.iterrows()
        ],
        "distribution": {
            "frequency": customers["frequency"].clip(upper=10).value_counts().sort_index().to_dict(),
        },
    }


def upload_customer_orders(connection: duckdb.DuckDBPyConnection, context: DatasetContext) -> pd.DataFrame:
    scopes = ("revenue", "date", "customer") + (() if context.grain == "transaction" else ("order",))
    cte_sql, parameters, _reasons = classified_cte(scopes, context, Filters())
    order_key = "CAST(_row_id AS VARCHAR)" if context.grain == "transaction" else "order_id"
    revenue = "order_value_once" if context.revenue_basis == "order_total" else "net_value"
    return connection.execute(
        f"""WITH {cte_sql.strip()}
SELECT customer_id, {order_key} AS order_key, MIN(order_ts) AS order_date, SUM({revenue}) AS revenue,
       BOOL_OR(NOT is_return) AS is_sale
FROM scoped
WHERE contributes
GROUP BY customer_id, {order_key}""",
        parameters,
    ).df()


def build_upload_customers(connection: duckdb.DuckDBPyConnection, context: DatasetContext) -> dict[str, Any]:
    for capability in ("customers", "trend", "revenue"):
        available, reason = context.capability(capability)
        if not available:
            return {"available": False, "reason": reason}
    orders = upload_customer_orders(connection, context)
    payload = customer_intelligence(orders, context.currency, context.orders_label.lower())
    if payload.get("available"):
        dashboard_revenue = compute_metric(connection, UPLOAD_METRICS_BY_ID["net_revenue"], context, Filters()).value
        payload["reconciliation"] = {
            "segment_revenue_total": payload["revenue_total"],
            "dashboard_label": "Dashboard net revenue",
            "dashboard_total": dashboard_revenue,
            "difference": None if dashboard_revenue is None else dashboard_revenue - payload["revenue_total"],
            "explanation": "Customer analytics needs a customer ID and a readable date on each row; rows without them count in the dashboard "
            "total but cannot be assigned to a customer, which is the only source of any difference.",
        }
    payload["scope_note"] = "Monetary value is net revenue after returns on contributing rows; frequency counts sale orders (returns-only orders excluded)."
    payload["redaction_note"] = "Customer identifiers are truncated in this view."
    return payload
