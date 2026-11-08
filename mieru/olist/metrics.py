from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from mieru.metrics.definitions import ExcludedRecords, MetricDefinition, MetricExplanation, RecordCounts, as_float
from mieru.olist.warehouse import OlistWarehouse
from src.analysis import lorenz_gini

OLIST_SOURCE: str = "olist"
OLIST_CURRENCY: str = "BRL"
MART_LINEAGE: tuple[str, ...] = (
    "data/raw/olist_orders_dataset.csv → raw_orders",
    "raw_orders ⋈ raw_customers (customer_unique_id) ⋈ order_items (pre-aggregated to order_id) ⋈ reviews (pre-aggregated to order_id)",
    "sql/01_mart_order_fulfillment.sql → mart_order_fulfillment (1 row per delivered order)",
)
DELIVERED_FILTER_EXCLUSION: str = (
    "Orders that are not 'delivered', or lack purchase / delivered / estimated dates, are excluded by the mart filter "
    "(see the upstream funnel)."
)
PIPELINE_FUNNEL_SQL: str = """
    SELECT
        COUNT(*) AS raw_orders,
        COUNT(*) FILTER (WHERE order_status <> 'delivered') AS not_delivered,
        COUNT(*) FILTER (
            WHERE order_status = 'delivered'
              AND (order_purchase_timestamp IS NULL OR order_delivered_customer_date IS NULL OR order_estimated_delivery_date IS NULL)
        ) AS delivered_missing_dates
    FROM raw_orders
"""


@dataclass(frozen=True)
class OlistMetric:
    definition: MetricDefinition
    sql: str
    exclusion_labels: dict[str, str] = field(default_factory=dict)
    lineage: tuple[str, ...] = MART_LINEAGE
    record_grain: str = "delivered order"
    value_transform: Callable[[Any, OlistWarehouse], float | None] | None = None
    is_currency: bool = False
    unavailable_reason: str | None = None


def olist_definition(
    metric_id: str,
    label: str,
    description: str,
    formula: str,
    unit: str,
    grain: str,
    source_columns: tuple[str, ...],
    exclusions: tuple[str, ...] = (DELIVERED_FILTER_EXCLUSION,),
    assumptions: tuple[str, ...] = (),
    limitations: tuple[str, ...] = (),
    transformations: tuple[str, ...] = (),
) -> MetricDefinition:
    return MetricDefinition(
        metric_id=metric_id,
        label=label,
        description=description,
        formula=formula,
        unit=unit,
        grain=grain,
        source=OLIST_SOURCE,
        source_columns=source_columns,
        transformations=transformations,
        exclusions=exclusions,
        assumptions=assumptions,
        limitations=limitations,
    )


def seller_gini_from_mart(_raw_value: Any, warehouse: OlistWarehouse) -> float | None:
    seller_gmv = warehouse.query_frame("SELECT seller_gmv FROM mart_seller_pareto")["seller_gmv"].to_numpy(dtype=float)
    return float(lorenz_gini(seller_gmv)) if len(seller_gmv) else None


ITEM_AGGREGATION_NOTE: str = "order_items pre-aggregated to order_id before joining (grain rule B), so no item fan-out."
OLIST_METRICS: tuple[OlistMetric, ...] = (
    OlistMetric(
        definition=olist_definition(
            "olist.gmv",
            "GMV",
            "Gross merchandise value of delivered orders: item prices plus freight charged to the customer.",
            "SUM(order_gmv) where order_gmv = Σ(price + freight_value) over the order's items",
            "currency",
            "order",
            ("olist_order_items_dataset.price", "olist_order_items_dataset.freight_value"),
            transformations=(ITEM_AGGREGATION_NOTE,),
            limitations=("GMV is not revenue or profit: it includes freight and seller proceeds, not Olist's commission.",),
        ),
        sql="""
            SELECT SUM(order_gmv) AS value, COUNT(*) AS input_records, COUNT(order_gmv) AS contributing_records,
                   COUNT(*) - COUNT(order_gmv) AS excluded_no_items
            FROM mart_order_fulfillment
        """,
        exclusion_labels={"no_items": "Delivered orders without item rows"},
        is_currency=True,
    ),
    OlistMetric(
        definition=olist_definition(
            "olist.product_sales",
            "Product sales",
            "Sum of item prices on delivered orders, excluding freight.",
            "SUM(items_price) where items_price = Σ price over the order's items",
            "currency",
            "order",
            ("olist_order_items_dataset.price",),
            transformations=(ITEM_AGGREGATION_NOTE,),
        ),
        sql="""
            SELECT SUM(items_price) AS value, COUNT(*) AS input_records, COUNT(items_price) AS contributing_records,
                   COUNT(*) - COUNT(items_price) AS excluded_no_items
            FROM mart_order_fulfillment
        """,
        exclusion_labels={"no_items": "Delivered orders without item rows"},
        is_currency=True,
    ),
    OlistMetric(
        definition=olist_definition(
            "olist.freight",
            "Freight charged",
            "Freight charged to customers on delivered orders.",
            "SUM(freight_value) over the order's items",
            "currency",
            "order",
            ("olist_order_items_dataset.freight_value",),
            transformations=(ITEM_AGGREGATION_NOTE,),
        ),
        sql="""
            SELECT SUM(freight_value) AS value, COUNT(*) AS input_records, COUNT(freight_value) AS contributing_records,
                   COUNT(*) - COUNT(freight_value) AS excluded_no_items
            FROM mart_order_fulfillment
        """,
        exclusion_labels={"no_items": "Delivered orders without item rows"},
        is_currency=True,
    ),
    OlistMetric(
        definition=olist_definition(
            "olist.payment_value",
            "Payments received",
            "Sum of payment records on delivered orders (all payment types, including vouchers).",
            "SUM(payment_value) over raw_order_payments joined to delivered orders",
            "currency",
            "payment record",
            ("olist_order_payments_dataset.payment_value",),
            limitations=(
                "Payment value is a different measure from GMV; small differences arise from installment interest and voucher rounding.",
            ),
        ),
        sql="""
            WITH delivered AS (SELECT order_id, order_gmv FROM mart_order_fulfillment),
            paid AS (
                SELECT p.order_id, p.payment_value FROM raw_order_payments AS p INNER JOIN delivered AS d ON d.order_id = p.order_id
            )
            SELECT SUM(payment_value) AS value,
                   COUNT(*) AS input_records,
                   COUNT(payment_value) AS contributing_records,
                   COUNT(*) - COUNT(payment_value) AS excluded_missing_value,
                   (SELECT COUNT(*) FROM delivered WHERE order_id NOT IN (SELECT order_id FROM paid)) AS context_delivered_orders_without_payment,
                   (SELECT SUM(order_gmv) FROM delivered) AS context_gmv_for_reconciliation
            FROM paid
        """,
        exclusion_labels={"missing_value": "Payment records without a value"},
        record_grain="payment record",
        lineage=(
            "data/raw/olist_order_payments_dataset.csv → raw_order_payments",
            "raw_order_payments ⋈ mart_order_fulfillment (delivered orders only)",
        ),
        is_currency=True,
    ),
    OlistMetric(
        definition=olist_definition(
            "olist.delivered_orders",
            "Delivered orders",
            "Orders with status 'delivered' and complete purchase, delivered and estimated-delivery dates.",
            "COUNT(*) over mart_order_fulfillment",
            "count",
            "order",
            ("olist_orders_dataset.order_id", "olist_orders_dataset.order_status"),
        ),
        sql="SELECT COUNT(*) AS value, COUNT(*) AS input_records, COUNT(*) AS contributing_records FROM mart_order_fulfillment",
    ),
    OlistMetric(
        definition=olist_definition(
            "olist.customers",
            "Unique customers",
            "Distinct people with at least one delivered order, resolved on customer_unique_id (customer_id is issued per order).",
            "COUNT(DISTINCT customer_unique_id)",
            "count",
            "customer",
            ("olist_customers_dataset.customer_unique_id",),
            transformations=("Grain rule D: customer_id → customer_unique_id entity resolution.",),
        ),
        sql="""
            SELECT COUNT(DISTINCT customer_unique_id) AS value, COUNT(*) AS input_records, COUNT(customer_unique_id) AS contributing_records,
                   COUNT(*) - COUNT(customer_unique_id) AS excluded_no_customer
            FROM mart_order_fulfillment
        """,
        exclusion_labels={"no_customer": "Orders without a resolvable customer"},
    ),
    OlistMetric(
        definition=olist_definition(
            "olist.aov",
            "Average order value",
            "Mean GMV per delivered order.",
            "SUM(order_gmv) / COUNT(order_gmv)",
            "currency",
            "order",
            ("olist_order_items_dataset.price", "olist_order_items_dataset.freight_value"),
            transformations=(ITEM_AGGREGATION_NOTE,),
        ),
        sql="""
            SELECT AVG(order_gmv) AS value, COUNT(*) AS input_records, COUNT(order_gmv) AS contributing_records,
                   COUNT(*) - COUNT(order_gmv) AS excluded_no_items
            FROM mart_order_fulfillment
        """,
        exclusion_labels={"no_items": "Delivered orders without item rows"},
        is_currency=True,
    ),
    OlistMetric(
        definition=olist_definition(
            "olist.sla_breach_rate",
            "SLA breach rate",
            "Share of delivered orders that arrived after the promised (estimated) delivery date.",
            "AVG(is_sla_breached) where is_sla_breached = sla_delay_days > 0 and "
            "sla_delay_days = DATE_DIFF('day', estimated_delivery_date, delivered_customer_date)",
            "ratio",
            "order",
            ("olist_orders_dataset.order_estimated_delivery_date", "olist_orders_dataset.order_delivered_customer_date"),
            transformations=("Timestamps cast to DATE before the whole-day difference.",),
        ),
        sql="""
            SELECT AVG(CAST(is_sla_breached AS DOUBLE)) AS value, COUNT(*) AS input_records,
                   COUNT(is_sla_breached) AS contributing_records
            FROM mart_order_fulfillment
        """,
    ),
    OlistMetric(
        definition=olist_definition(
            "olist.mean_review_score",
            "Mean review score",
            "Average review score (1–5) over reviewed delivered orders; multiple reviews of one order are averaged first.",
            "AVG(review_score) where review_score = AVG(review_score) per order_id",
            "score",
            "order",
            ("olist_order_reviews_dataset.review_score",),
            transformations=("Grain rule C: reviews pre-aggregated to order_id (547 orders have more than one review).",),
        ),
        sql="""
            SELECT AVG(review_score) AS value, COUNT(*) AS input_records, COUNT(review_score) AS contributing_records,
                   COUNT(*) - COUNT(review_score) AS excluded_no_review
            FROM mart_order_fulfillment
        """,
        exclusion_labels={"no_review": "Delivered orders without a review"},
    ),
    OlistMetric(
        definition=olist_definition(
            "olist.severe_detractor_rate",
            "Severe detractor rate",
            "Share of reviewed delivered orders whose (order-level mean) review score is 1–2 stars.",
            "AVG(is_severe_detractor) where is_severe_detractor = review_score <= 2.0 (NULL when unreviewed)",
            "ratio",
            "order",
            ("olist_order_reviews_dataset.review_score",),
        ),
        sql="""
            SELECT AVG(CAST(is_severe_detractor AS DOUBLE)) AS value, COUNT(*) AS input_records,
                   COUNT(is_severe_detractor) AS contributing_records,
                   COUNT(*) - COUNT(is_severe_detractor) AS excluded_no_review
            FROM mart_order_fulfillment
        """,
        exclusion_labels={"no_review": "Delivered orders without a review"},
    ),
    OlistMetric(
        definition=olist_definition(
            "olist.repeat_purchase_rate",
            "Repeat purchase rate",
            "Share of customers (customer_unique_id) with two or more delivered orders.",
            "AVG(is_repeat_buyer) over each customer's first delivered order (customer_order_seq = 1)",
            "ratio",
            "customer",
            ("olist_customers_dataset.customer_unique_id", "olist_orders_dataset.order_purchase_timestamp"),
            limitations=(
                "Counts a repeat at any time before the data ends, so older customers have more time to repeat (right-censoring). "
                "The research uses a fixed 180-day horizon for causal comparisons.",
                "786 of the 2,801 repeat customers placed all their orders on the same day (basket splits).",
            ),
        ),
        sql="""
            SELECT AVG(CAST(is_repeat_buyer AS DOUBLE)) FILTER (WHERE customer_order_seq = 1) AS value,
                   COUNT(*) AS input_records,
                   COUNT(*) FILTER (WHERE customer_order_seq = 1) AS contributing_records,
                   COUNT(*) FILTER (WHERE customer_order_seq > 1) AS excluded_later_orders
            FROM mart_order_fulfillment
        """,
        exclusion_labels={"later_orders": "Second and later orders (each customer is counted once, on the first order)"},
    ),
    OlistMetric(
        definition=olist_definition(
            "olist.median_delivery_days",
            "Median delivery time",
            "Median whole days from purchase to delivery to the customer.",
            "MEDIAN(DATE_DIFF('day', purchase_date, delivered_customer_date))",
            "days",
            "order",
            ("olist_orders_dataset.order_purchase_timestamp", "olist_orders_dataset.order_delivered_customer_date"),
        ),
        sql="""
            SELECT MEDIAN(actual_delivery_days) AS value, COUNT(*) AS input_records,
                   COUNT(actual_delivery_days) AS contributing_records
            FROM mart_order_fulfillment
        """,
    ),
    OlistMetric(
        definition=olist_definition(
            "olist.active_sellers",
            "Active sellers",
            "Sellers with at least one item on a delivered order.",
            "COUNT(*) over mart_seller_pareto (one row per seller)",
            "count",
            "seller",
            ("olist_order_items_dataset.seller_id",),
        ),
        sql="SELECT COUNT(*) AS value, COUNT(*) AS input_records, COUNT(*) AS contributing_records FROM mart_seller_pareto",
        record_grain="seller",
        lineage=MART_LINEAGE + ("sql/03_mart_seller_pareto.sql → mart_seller_pareto (1 row per seller)",),
    ),
    OlistMetric(
        definition=olist_definition(
            "olist.seller_gmv_gini",
            "Seller GMV Gini",
            "Inequality of GMV across sellers (0 = perfectly equal, 1 = one seller has everything).",
            "1 − 2·trapezoid(cumulative GMV share, cumulative seller share), sellers ascending by GMV, [0,0] prepended",
            "index",
            "seller",
            ("olist_order_items_dataset.seller_id", "olist_order_items_dataset.price", "olist_order_items_dataset.freight_value"),
            transformations=("Computed in Python by src.analysis.lorenz_gini on mart_seller_pareto.seller_gmv.",),
        ),
        sql="SELECT NULL AS value, COUNT(*) AS input_records, COUNT(seller_gmv) AS contributing_records FROM mart_seller_pareto",
        record_grain="seller",
        lineage=MART_LINEAGE + ("sql/03_mart_seller_pareto.sql → mart_seller_pareto (1 row per seller)",),
        value_transform=seller_gini_from_mart,
    ),
    OlistMetric(
        definition=olist_definition(
            "olist.seller_share_for_80pct_gmv",
            "Sellers generating 80% of GMV",
            "Smallest share of sellers (ranked by GMV) whose cumulative GMV reaches 80% of the platform total.",
            "MIN(seller_rank WHERE cumulative_gmv_share >= 0.80) / COUNT(sellers)",
            "share",
            "seller",
            ("olist_order_items_dataset.seller_id", "olist_order_items_dataset.price", "olist_order_items_dataset.freight_value"),
        ),
        sql="""
            SELECT CAST(MIN(seller_rank) FILTER (WHERE cumulative_gmv_share >= 0.8 - 1e-12) AS DOUBLE) / COUNT(*) AS value,
                   COUNT(*) AS input_records, COUNT(*) AS contributing_records
            FROM mart_seller_pareto
        """,
        record_grain="seller",
        lineage=MART_LINEAGE + ("sql/03_mart_seller_pareto.sql → mart_seller_pareto (window-function Pareto ranking)",),
    ),
    OlistMetric(
        definition=olist_definition(
            "olist.gross_profit",
            "Gross profit",
            "Revenue minus cost of goods sold.",
            "Not computable",
            "currency",
            "order",
            (),
            exclusions=(),
            limitations=("The Olist dataset contains no product cost or commission data.",),
        ),
        sql="",
        unavailable_reason="The Olist public dataset has no cost or commission columns, so profit cannot be calculated without inventing values.",
        is_currency=True,
    ),
)
OLIST_METRICS_BY_ID: dict[str, OlistMetric] = {metric.definition.metric_id: metric for metric in OLIST_METRICS}


def explain_olist_metric(warehouse: OlistWarehouse, metric_id: str) -> MetricExplanation:
    metric = OLIST_METRICS_BY_ID[metric_id]
    currency = OLIST_CURRENCY if metric.is_currency else None
    if metric.unavailable_reason:
        return MetricExplanation(
            definition=metric.definition,
            status="unavailable",
            value=None,
            sql="",
            record_counts=None,
            lineage=[],
            unavailable_reason=metric.unavailable_reason,
            currency=currency,
        )
    row = warehouse.query_one(metric.sql)
    excluded = [
        ExcludedRecords(reason=reason, label=label, records=int(row[f"excluded_{reason}"] or 0))
        for reason, label in metric.exclusion_labels.items()
    ]
    record_counts = RecordCounts(
        grain=metric.record_grain,
        input_records=int(row["input_records"]),
        contributing_records=int(row["contributing_records"]),
        excluded=excluded,
    )
    raw_value = row.get("value")
    value = metric.value_transform(raw_value, warehouse) if metric.value_transform else as_float(raw_value)
    funnel = warehouse.query_one(PIPELINE_FUNNEL_SQL)
    context = {key[len("context_"):]: (as_float(item) if isinstance(item, (float, np.floating)) else item) for key, item in row.items() if key.startswith("context_")}
    context["upstream_funnel"] = {
        "raw_orders": int(funnel["raw_orders"]),
        "excluded_not_delivered": int(funnel["not_delivered"]),
        "excluded_delivered_missing_dates": int(funnel["delivered_missing_dates"]),
        "delivered_orders_in_mart": int(funnel["raw_orders"]) - int(funnel["not_delivered"]) - int(funnel["delivered_missing_dates"]),
    }
    return MetricExplanation(
        definition=metric.definition,
        status="ok",
        value=value,
        sql=" ".join(metric.sql.split()),
        record_counts=record_counts,
        lineage=list(metric.lineage),
        currency=currency,
        context=context,
    )


def olist_metric_value(warehouse: OlistWarehouse, metric_id: str) -> float | None:
    return explain_olist_metric(warehouse, metric_id).value
