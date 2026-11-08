from typing import Any

import pandas as pd
from scipy import stats

from mieru.olist.metrics import OLIST_CURRENCY
from mieru.olist.service import BRAZIL_STATE_NAMES, clean_value, prettify_category
from mieru.olist.warehouse import OlistWarehouse
from src.analysis import proportion_summary

MIN_CATEGORY_ORDERS: int = 200
MIN_STATE_ORDERS: int = 500
CATEGORY_OUTCOMES_SQL: str = """
WITH category_orders AS (
    SELECT
        COALESCE(NULLIF(TRIM(p.product_category_name), ''), 'uncategorized') AS category,
        f.order_id,
        ANY_VALUE(f.review_score) AS review_score,
        ANY_VALUE(f.is_severe_detractor) AS is_severe_detractor,
        ANY_VALUE(f.is_sla_breached) AS is_sla_breached
    FROM raw_order_items AS oi
    INNER JOIN mart_order_fulfillment AS f
        ON f.order_id = oi.order_id
    LEFT JOIN raw_products AS p
        ON p.product_id = oi.product_id
    GROUP BY 1, 2
)
SELECT
    category,
    COUNT(*) AS outcome_orders,
    COUNT(review_score) AS reviewed_orders,
    SUM(CAST(is_severe_detractor AS INTEGER)) AS severe_detractors,
    SUM(CAST(is_sla_breached AS INTEGER)) AS breached_orders
FROM category_orders
GROUP BY 1
"""
STATE_OUTCOMES_SQL: str = """
SELECT
    customer_state,
    COUNT(*) AS outcome_orders,
    COUNT(review_score) AS reviewed_orders,
    SUM(CAST(is_severe_detractor AS INTEGER)) AS severe_detractors,
    SUM(CAST(is_sla_breached AS INTEGER)) AS breached_orders
FROM mart_order_fulfillment
GROUP BY 1
"""


def rate_interval(events: Any, trials: Any) -> dict[str, float | None]:
    summary = proportion_summary(int(events or 0), int(trials or 0))
    if summary["rate_pct"] is None:
        return {"rate": None, "ci_low": None, "ci_high": None}
    rate = float(summary["rate_pct"]) / 100
    return {
        "rate": rate,
        "ci_low": min(rate, float(summary["ci_low_pct"]) / 100),
        "ci_high": max(rate, float(summary["ci_high_pct"]) / 100),
    }


def spearman(frame: pd.DataFrame, x_column: str, y_column: str, description: str) -> dict[str, Any]:
    usable = frame[[x_column, y_column]].dropna()
    if len(usable) < 5:
        return {"available": False, "reason": "Fewer than five groups meet the minimum size."}
    result = stats.spearmanr(usable[x_column], usable[y_column])
    return {
        "available": True,
        "rho": float(result.statistic),
        "p_value": float(result.pvalue),
        "n_groups": int(len(usable)),
        "description": description,
        "caveat": "A cross-sectional association between groups, not evidence that one causes the other.",
    }


def build_category_scorecard(warehouse: OlistWarehouse) -> dict[str, Any]:
    categories = warehouse.query_frame(
        "SELECT category, orders, items_sold, gmv, gmv_share, product_sales, freight, freight_share, average_item_price, "
        "mean_review_score, sla_breach_rate, mean_delivery_days, gmv_rank FROM mart_olist_category"
    )
    outcomes = warehouse.query_frame(CATEGORY_OUTCOMES_SQL)
    merged = categories.merge(outcomes, on="category", how="left", validate="one_to_one").sort_values("gmv_rank")
    merged["display_name"] = merged["category"].map(prettify_category)
    merged["reliable"] = merged["orders"] >= MIN_CATEGORY_ORDERS
    rows = []
    for record in merged.to_dict(orient="records"):
        breach = rate_interval(record["breached_orders"], record["outcome_orders"])
        severe = rate_interval(record["severe_detractors"], record["reviewed_orders"])
        rows.append(
            {
                **{key: clean_value(record[key]) for key in ("category", "display_name", "orders", "items_sold", "gmv", "gmv_share", "freight_share", "average_item_price", "mean_review_score", "mean_delivery_days", "gmv_rank")},
                "reliable": bool(record["reliable"]),
                "reviewed_orders": int(record["reviewed_orders"]),
                "sla_breach_rate": breach["rate"],
                "sla_breach_ci": [breach["ci_low"], breach["ci_high"]],
                "severe_detractor_rate": severe["rate"],
                "severe_detractor_ci": [severe["ci_low"], severe["ci_high"]],
            }
        )
    reliable = [row for row in rows if row["reliable"] and row["mean_review_score"] is not None]
    ranked_by_review = sorted(reliable, key=lambda row: (-row["mean_review_score"], row["category"]))
    reliable_frame = pd.DataFrame(reliable)
    return {
        "rows": rows,
        "total_categories": len(rows),
        "reliable_categories": len(reliable),
        "min_orders": MIN_CATEGORY_ORDERS,
        "gmv_total": float(merged["gmv"].sum()),
        "best_reviewed": ranked_by_review[:3],
        "worst_reviewed": ranked_by_review[-3:][::-1],
        "association": spearman(
            reliable_frame, "sla_breach_rate", "mean_review_score", f"SLA breach rate vs mean review score across categories with at least {MIN_CATEGORY_ORDERS} orders"
        )
        if len(reliable_frame)
        else {"available": False, "reason": "No category meets the minimum size."},
        "note": (
            f"Category GMV is item-grain (price + freight) and sums to platform GMV. Review and SLA outcomes count each order once per category. "
            f"Rates for categories with fewer than {MIN_CATEGORY_ORDERS} orders are shown but not ranked."
        ),
    }


def build_state_scorecard(warehouse: OlistWarehouse) -> dict[str, Any]:
    states = warehouse.query_frame(
        "SELECT customer_state, delivered_orders, customers, gmv, gmv_share, average_order_value, mean_review_score, "
        "median_delivery_days, median_promised_days, median_distance_km, mean_freight_ratio FROM mart_olist_state"
    )
    outcomes = warehouse.query_frame(STATE_OUTCOMES_SQL)
    merged = states.merge(outcomes, on="customer_state", how="left", validate="one_to_one").sort_values("gmv", ascending=False)
    rows = []
    for record in merged.to_dict(orient="records"):
        breach = rate_interval(record["breached_orders"], record["outcome_orders"])
        severe = rate_interval(record["severe_detractors"], record["reviewed_orders"])
        rows.append(
            {
                "state": record["customer_state"],
                "state_name": BRAZIL_STATE_NAMES.get(record["customer_state"], record["customer_state"]),
                **{key: clean_value(record[key]) for key in ("delivered_orders", "customers", "gmv", "gmv_share", "average_order_value", "mean_review_score", "median_delivery_days", "median_promised_days", "median_distance_km", "mean_freight_ratio")},
                "reliable": int(record["delivered_orders"]) >= MIN_STATE_ORDERS,
                "sla_breach_rate": breach["rate"],
                "sla_breach_ci": [breach["ci_low"], breach["ci_high"]],
                "severe_detractor_rate": severe["rate"],
                "severe_detractor_ci": [severe["ci_low"], severe["ci_high"]],
            }
        )
    reliable_frame = pd.DataFrame([row for row in rows if row["reliable"]])
    return {
        "rows": rows,
        "total_states": len(rows),
        "reliable_states": int(len(reliable_frame)),
        "min_orders": MIN_STATE_ORDERS,
        "gmv_total": float(merged["gmv"].sum()),
        "orders_total": int(merged["delivered_orders"].sum()),
        "association": spearman(
            reliable_frame, "median_delivery_days", "mean_review_score", f"Median delivery days vs mean review score across states with at least {MIN_STATE_ORDERS} orders"
        ),
        "note": f"Customer state of each delivered order. States with fewer than {MIN_STATE_ORDERS} orders are shown but excluded from the association.",
    }


def build_markets(warehouse: OlistWarehouse) -> dict[str, Any]:
    return {
        "currency": OLIST_CURRENCY,
        "categories": build_category_scorecard(warehouse),
        "states": build_state_scorecard(warehouse),
    }
