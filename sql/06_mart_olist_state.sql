-- mart_olist_state: one row per customer state over delivered orders (order grain).
-- customers counts distinct customer_unique_id within the state; a customer who ordered from two states counts in both,
-- so state customer counts are not additive to the platform total.
CREATE OR REPLACE TABLE mart_olist_state AS
SELECT
    customer_state,
    COUNT(*) AS delivered_orders,
    COUNT(DISTINCT customer_unique_id) AS customers,
    SUM(order_gmv) AS gmv,
    SUM(order_gmv) / SUM(SUM(order_gmv)) OVER () AS gmv_share,
    AVG(order_gmv) AS average_order_value,
    AVG(CAST(is_sla_breached AS DOUBLE)) AS sla_breach_rate,
    AVG(review_score) AS mean_review_score,
    AVG(CAST(is_severe_detractor AS DOUBLE)) AS severe_detractor_rate,
    MEDIAN(actual_delivery_days) AS median_delivery_days,
    MEDIAN(promised_sla_days) AS median_promised_days,
    MEDIAN(delivery_distance_km) AS median_distance_km,
    AVG(freight_ratio) AS mean_freight_ratio
FROM mart_order_fulfillment
GROUP BY customer_state
ORDER BY gmv DESC;
