-- mart_olist_category: one row per product category over items of delivered orders.
-- Financial sums are item-grain (each item belongs to exactly one category, so category GMV sums to platform GMV).
-- Order outcomes (review, SLA) are collapsed to (category, order) first so an order counts once per category.
CREATE OR REPLACE TABLE mart_olist_category AS
WITH delivered_items AS (
    SELECT
        oi.order_id,
        oi.price,
        oi.freight_value,
        COALESCE(NULLIF(TRIM(p.product_category_name), ''), 'uncategorized') AS category,
        f.review_score,
        f.is_sla_breached,
        f.actual_delivery_days
    FROM raw_order_items AS oi
    INNER JOIN mart_order_fulfillment AS f
        ON f.order_id = oi.order_id
    LEFT JOIN raw_products AS p
        ON p.product_id = oi.product_id
),
category_items AS (
    SELECT
        category,
        COUNT(*) AS items_sold,
        SUM(price + freight_value) AS gmv,
        SUM(price) AS product_sales,
        SUM(freight_value) AS freight,
        AVG(price) AS average_item_price
    FROM delivered_items
    GROUP BY category
),
category_orders AS (
    SELECT
        category,
        order_id,
        ANY_VALUE(review_score) AS review_score,
        ANY_VALUE(is_sla_breached) AS is_sla_breached,
        ANY_VALUE(actual_delivery_days) AS actual_delivery_days
    FROM delivered_items
    GROUP BY category, order_id
),
category_outcomes AS (
    SELECT
        category,
        COUNT(*) AS orders,
        AVG(review_score) AS mean_review_score,
        AVG(CAST(is_sla_breached AS DOUBLE)) AS sla_breach_rate,
        AVG(CAST(actual_delivery_days AS DOUBLE)) AS mean_delivery_days
    FROM category_orders
    GROUP BY category
)
SELECT
    i.category,
    o.orders,
    i.items_sold,
    i.gmv,
    i.product_sales,
    i.freight,
    i.freight / NULLIF(i.gmv, 0) AS freight_share,
    i.average_item_price,
    o.mean_review_score,
    o.sla_breach_rate,
    o.mean_delivery_days,
    i.gmv / SUM(i.gmv) OVER () AS gmv_share,
    ROW_NUMBER() OVER (ORDER BY i.gmv DESC, i.category) AS gmv_rank
FROM category_items AS i
INNER JOIN category_outcomes AS o
    ON o.category = i.category
ORDER BY gmv_rank;
