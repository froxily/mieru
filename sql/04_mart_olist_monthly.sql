-- mart_olist_monthly: one row per purchase month over delivered orders (mart_order_fulfillment grain = 1 row per order).
-- is_partial marks months that must not be read as genuine trend movements: the sparse 2016 launch tail and the
-- final snapshot month (purchases end before month-end and late orders were still undelivered at extraction).
CREATE OR REPLACE TABLE mart_olist_monthly AS
WITH monthly AS (
    SELECT
        purchase_month,
        COUNT(*) AS delivered_orders,
        COUNT(DISTINCT customer_unique_id) AS active_customers,
        COUNT(*) FILTER (WHERE customer_order_seq = 1) AS first_time_customers,
        SUM(order_gmv) AS gmv,
        SUM(items_price) AS product_sales,
        SUM(freight_value) AS freight,
        AVG(order_gmv) AS average_order_value,
        AVG(CAST(is_sla_breached AS DOUBLE)) AS sla_breach_rate,
        AVG(review_score) AS mean_review_score,
        AVG(CAST(is_severe_detractor AS DOUBLE)) AS severe_detractor_rate,
        MEDIAN(actual_delivery_days) AS median_delivery_days,
        MEDIAN(promised_sla_days) AS median_promised_days,
        MAX(order_purchase_timestamp) AS last_purchase_ts
    FROM mart_order_fulfillment
    GROUP BY purchase_month
),
bounds AS (
    SELECT MAX(purchase_month) AS final_month FROM monthly
)
SELECT
    m.purchase_month,
    m.delivered_orders,
    m.active_customers,
    m.first_time_customers,
    m.gmv,
    m.product_sales,
    m.freight,
    m.average_order_value,
    m.sla_breach_rate,
    m.mean_review_score,
    m.severe_detractor_rate,
    m.median_delivery_days,
    m.median_promised_days,
    CASE
        WHEN m.purchase_month < DATE '2017-01-01' THEN TRUE
        WHEN m.purchase_month = b.final_month THEN TRUE
        ELSE FALSE
    END AS is_partial,
    CASE
        WHEN m.purchase_month < DATE '2017-01-01' THEN 'Sparse 2016 launch period (excluded from the research window)'
        WHEN m.purchase_month = b.final_month THEN 'Final snapshot month: purchases end ' || strftime(m.last_purchase_ts, '%Y-%m-%d') || ' and some orders were not yet delivered'
        ELSE NULL
    END AS coverage_note
FROM monthly AS m
CROSS JOIN bounds AS b
ORDER BY m.purchase_month;
