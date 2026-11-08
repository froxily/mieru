-- mart_seller_pareto: one row per seller with delivered-order unit economics and Pareto ranking.
-- Items are first collapsed to (seller_id, order_id) so order-level SLA / review outcomes are
-- weighted once per seller-order, never once per item.
CREATE OR REPLACE TABLE mart_seller_pareto AS
WITH seller_orders AS (
    SELECT
        oi.seller_id,
        oi.order_id,
        COUNT(*) AS items_in_order,
        SUM(oi.price + oi.freight_value) AS seller_order_gmv,
        ANY_VALUE(f.is_sla_breached) AS is_sla_breached,
        ANY_VALUE(f.review_score) AS review_score,
        ANY_VALUE(f.actual_delivery_days) AS actual_delivery_days
    FROM raw_order_items AS oi
    INNER JOIN mart_order_fulfillment AS f
        ON f.order_id = oi.order_id
    GROUP BY oi.seller_id, oi.order_id
),
seller_agg AS (
    SELECT
        seller_id,
        COUNT(*) AS total_orders,
        SUM(items_in_order) AS total_items,
        SUM(seller_order_gmv) AS seller_gmv,
        SUM(is_sla_breached) AS breached_orders,
        AVG(CAST(is_sla_breached AS DOUBLE)) AS sla_breach_rate,
        COUNT(review_score) AS reviewed_orders,
        AVG(review_score) AS mean_review_score,
        AVG(CAST(actual_delivery_days AS DOUBLE)) AS mean_delivery_days
    FROM seller_orders
    GROUP BY seller_id
),
ranked AS (
    SELECT
        *,
        ROW_NUMBER() OVER (ORDER BY seller_gmv DESC, seller_id ASC) AS seller_rank,
        COUNT(*) OVER () AS seller_count,
        SUM(seller_gmv) OVER (
            ORDER BY seller_gmv DESC, seller_id ASC
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS cumulative_gmv,
        SUM(seller_gmv) OVER () AS platform_gmv
    FROM seller_agg
)
SELECT
    seller_id,
    total_orders,
    total_items,
    seller_gmv,
    breached_orders,
    sla_breach_rate,
    reviewed_orders,
    mean_review_score,
    mean_delivery_days,
    seller_rank,
    CAST(seller_rank AS DOUBLE) / seller_count AS seller_percentile,
    cumulative_gmv,
    cumulative_gmv / platform_gmv AS cumulative_gmv_share,
    CASE
        WHEN CAST(seller_rank AS DOUBLE) / seller_count <= 0.10 THEN 'Top 10% Sellers'
        WHEN CAST(seller_rank AS DOUBLE) / seller_count <= 0.50 THEN 'Middle 40% Sellers'
        ELSE 'Bottom 50% Long-Tail'
    END AS pareto_tier
FROM ranked
ORDER BY seller_rank;
