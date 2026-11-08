-- mart_order_fulfillment: strictly one row per delivered order_id.
-- Grain rules: (A) geolocation deduplicated to one centroid per zip prefix,
-- (B) order_items pre-aggregated to order_id, (C) reviews pre-aggregated to order_id,
-- (D) customer entity resolution on customer_unique_id (customer_id is per-order in Olist).
CREATE OR REPLACE TABLE mart_order_fulfillment AS
WITH dedup_geo AS (
    SELECT
        geolocation_zip_code_prefix AS zip_code_prefix,
        AVG(geolocation_lat) AS lat,
        AVG(geolocation_lng) AS lng,
        COUNT(*) AS geolocation_points
    FROM raw_geolocation
    WHERE geolocation_lat BETWEEN -35.0 AND 5.5
      AND geolocation_lng BETWEEN -75.0 AND -33.0
    GROUP BY geolocation_zip_code_prefix
),
order_items_agg AS (
    SELECT
        order_id,
        COUNT(*) AS item_count,
        SUM(price) AS items_price,
        SUM(freight_value) AS freight_value,
        SUM(price + freight_value) AS order_gmv,
        SUM(freight_value) / NULLIF(SUM(price + freight_value), 0) AS freight_ratio,
        ARG_MAX(seller_id, price) AS primary_seller_id,
        COUNT(DISTINCT seller_id) AS seller_count
    FROM raw_order_items
    GROUP BY order_id
),
reviews_agg AS (
    SELECT
        order_id,
        AVG(CAST(review_score AS DOUBLE)) AS review_score,
        COUNT(*) AS review_count
    FROM raw_order_reviews
    GROUP BY order_id
),
delivered_orders AS (
    SELECT
        o.order_id,
        o.customer_id,
        c.customer_unique_id,
        c.customer_zip_code_prefix,
        c.customer_state,
        o.order_purchase_timestamp,
        o.order_approved_at,
        o.order_delivered_carrier_date,
        o.order_delivered_customer_date,
        o.order_estimated_delivery_date
    FROM raw_orders AS o
    INNER JOIN raw_customers AS c
        ON c.customer_id = o.customer_id
    WHERE o.order_status = 'delivered'
      AND o.order_purchase_timestamp IS NOT NULL
      AND o.order_delivered_customer_date IS NOT NULL
      AND o.order_estimated_delivery_date IS NOT NULL
),
customer_sequenced AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY customer_unique_id
            ORDER BY order_purchase_timestamp ASC, order_id ASC
        ) AS customer_order_seq,
        COUNT(*) OVER (PARTITION BY customer_unique_id) AS customer_total_orders,
        CASE WHEN COUNT(*) OVER (PARTITION BY customer_unique_id) >= 2 THEN 1 ELSE 0 END AS is_repeat_buyer
    FROM delivered_orders
),
-- Timing-clean retention: the first later order placed AFTER this order reached the customer.
-- Same-day basket splits (a second order_id placed before the first was delivered) are not counted here.
post_delivery_repeat AS (
    SELECT
        base.order_id,
        MIN(later.order_purchase_timestamp) AS next_purchase_after_delivery_ts
    FROM delivered_orders AS base
    INNER JOIN delivered_orders AS later
        ON later.customer_unique_id = base.customer_unique_id
       AND later.order_purchase_timestamp > base.order_delivered_customer_date
    GROUP BY base.order_id
),
observation_window AS (
    SELECT MAX(order_purchase_timestamp) AS data_end_ts
    FROM delivered_orders
),
fulfillment_base AS (
    SELECT
        cs.order_id,
        cs.customer_id,
        cs.customer_unique_id,
        cs.customer_state,
        cs.customer_zip_code_prefix,
        oi.primary_seller_id,
        s.seller_state AS primary_seller_state,
        s.seller_zip_code_prefix AS primary_seller_zip_code_prefix,
        cs.order_purchase_timestamp,
        cs.order_approved_at,
        cs.order_delivered_carrier_date,
        cs.order_delivered_customer_date,
        cs.order_estimated_delivery_date,
        CAST(DATE_TRUNC('month', CAST(cs.order_purchase_timestamp AS DATE)) AS DATE) AS purchase_month,
        cs.customer_order_seq,
        cs.customer_total_orders,
        cs.is_repeat_buyer,
        CASE WHEN pdr.next_purchase_after_delivery_ts IS NOT NULL THEN 1 ELSE 0 END AS is_repeat_after_delivery,
        pdr.next_purchase_after_delivery_ts,
        DATE_DIFF('day', CAST(cs.order_delivered_customer_date AS DATE), CAST(pdr.next_purchase_after_delivery_ts AS DATE)) AS days_to_post_delivery_repeat,
        DATE_DIFF('day', CAST(cs.order_delivered_customer_date AS DATE), CAST(ow.data_end_ts AS DATE)) AS post_delivery_followup_days,
        oi.item_count,
        oi.seller_count,
        oi.items_price,
        oi.freight_value,
        oi.order_gmv,
        oi.freight_ratio,
        r.review_score,
        r.review_count,
        DATE_DIFF('day', CAST(cs.order_purchase_timestamp AS DATE), CAST(cs.order_delivered_customer_date AS DATE)) AS actual_delivery_days,
        DATE_DIFF('day', CAST(cs.order_purchase_timestamp AS DATE), CAST(cs.order_estimated_delivery_date AS DATE)) AS promised_sla_days,
        DATE_DIFF('day', CAST(cs.order_estimated_delivery_date AS DATE), CAST(cs.order_delivered_customer_date AS DATE)) AS sla_delay_days,
        cg.lat AS c_lat,
        cg.lng AS c_lng,
        sg.lat AS s_lat,
        sg.lng AS s_lng
    FROM customer_sequenced AS cs
    CROSS JOIN observation_window AS ow
    LEFT JOIN post_delivery_repeat AS pdr
        ON pdr.order_id = cs.order_id
    LEFT JOIN order_items_agg AS oi
        ON oi.order_id = cs.order_id
    LEFT JOIN reviews_agg AS r
        ON r.order_id = cs.order_id
    LEFT JOIN raw_sellers AS s
        ON s.seller_id = oi.primary_seller_id
    LEFT JOIN dedup_geo AS cg
        ON cg.zip_code_prefix = cs.customer_zip_code_prefix
    LEFT JOIN dedup_geo AS sg
        ON sg.zip_code_prefix = s.seller_zip_code_prefix
)
SELECT
    order_id,
    customer_id,
    customer_unique_id,
    customer_state,
    customer_zip_code_prefix,
    primary_seller_id,
    primary_seller_state,
    primary_seller_zip_code_prefix,
    order_purchase_timestamp,
    order_approved_at,
    order_delivered_carrier_date,
    order_delivered_customer_date,
    order_estimated_delivery_date,
    purchase_month,
    customer_order_seq,
    customer_total_orders,
    is_repeat_buyer,
    is_repeat_after_delivery,
    next_purchase_after_delivery_ts,
    days_to_post_delivery_repeat,
    post_delivery_followup_days,
    CASE
        WHEN post_delivery_followup_days < 180 THEN NULL
        WHEN days_to_post_delivery_repeat <= 180 THEN 1
        ELSE 0
    END AS is_repeat_within_180d_after_delivery,
    item_count,
    seller_count,
    items_price,
    freight_value,
    order_gmv,
    freight_ratio,
    review_score,
    review_count,
    actual_delivery_days,
    promised_sla_days,
    sla_delay_days,
    CASE WHEN sla_delay_days > 0 THEN 1 ELSE 0 END AS is_sla_breached,
    CASE
        WHEN review_score IS NULL THEN NULL
        WHEN review_score <= 2.0 THEN 1
        ELSE 0
    END AS is_severe_detractor,
    CASE
        WHEN review_score IS NULL THEN NULL
        WHEN review_score >= 4.5 THEN 1
        ELSE 0
    END AS is_five_star,
    CASE
        WHEN sla_delay_days < -7 THEN '1. >7d Early'
        WHEN sla_delay_days BETWEEN -7 AND -1 THEN '2. 1-7d Early'
        WHEN sla_delay_days = 0 THEN '3. On Time (Day 0)'
        WHEN sla_delay_days BETWEEN 1 AND 3 THEN '4. 1-3d Late'
        WHEN sla_delay_days BETWEEN 4 AND 7 THEN '5. 4-7d Late'
        ELSE '6. >7d Late'
    END AS sla_delay_bucket,
    c_lat,
    c_lng,
    s_lat,
    s_lng,
    -- DuckDB GREATEST/LEAST ignore NULL arguments, so missing centroids must be short-circuited
    -- explicitly; otherwise the clamp returns ACOS(-1) and a fake ~20,015 km antipodal distance.
    CASE
        WHEN c_lat IS NULL OR c_lng IS NULL OR s_lat IS NULL OR s_lng IS NULL THEN NULL
        ELSE 6371.0 * ACOS(LEAST(1.0, GREATEST(-1.0,
            1.0 - 2.0 * (
                POWER(SIN(RADIANS(s_lat - c_lat) / 2.0), 2)
                + COS(RADIANS(c_lat)) * COS(RADIANS(s_lat)) * POWER(SIN(RADIANS(s_lng - c_lng) / 2.0), 2)
            )
        )))
    END AS delivery_distance_km
FROM fulfillment_base
ORDER BY order_purchase_timestamp, order_id;
