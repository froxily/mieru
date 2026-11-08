-- mart_cohort_retention: one row per (cohort_month, period_number) for acquisition cohorts 2017-01..2018-08.
-- The cohort is anchored on each customer_unique_id's TRUE first delivered order (so 2016 buyers are not
-- re-labelled as new 2017 buyers); activity is restricted to the 2017-01-01..2018-08-31 window.
-- Every observable cell is emitted (zero-filled); right-censored cells (cohort_month + period > 2018-08) are omitted.
CREATE OR REPLACE TABLE mart_cohort_retention AS
WITH customer_first_purchase AS (
    SELECT
        customer_unique_id,
        CAST(DATE_TRUNC('month', MIN(CAST(order_purchase_timestamp AS DATE))) AS DATE) AS cohort_month
    FROM mart_order_fulfillment
    GROUP BY customer_unique_id
),
cohort_activity AS (
    SELECT
        f.customer_unique_id,
        fp.cohort_month,
        CAST(DATE_TRUNC('month', CAST(f.order_purchase_timestamp AS DATE)) AS DATE) AS activity_month,
        DATE_DIFF(
            'month',
            fp.cohort_month,
            DATE_TRUNC('month', CAST(f.order_purchase_timestamp AS DATE))
        ) AS period_number,
        f.order_gmv
    FROM mart_order_fulfillment AS f
    INNER JOIN customer_first_purchase AS fp
        ON fp.customer_unique_id = f.customer_unique_id
    WHERE CAST(f.order_purchase_timestamp AS DATE) BETWEEN DATE '2017-01-01' AND DATE '2018-08-31'
      AND fp.cohort_month BETWEEN DATE '2017-01-01' AND DATE '2018-08-01'
),
cohort_sizes AS (
    SELECT
        cohort_month,
        COUNT(DISTINCT customer_unique_id) AS cohort_size
    FROM cohort_activity
    WHERE period_number = 0
    GROUP BY cohort_month
),
observable_grid AS (
    SELECT
        cs.cohort_month,
        CAST(p.range AS INTEGER) AS period_number,
        cs.cohort_size
    FROM cohort_sizes AS cs
    CROSS JOIN range(0, 12) AS p
    WHERE p.range <= DATE_DIFF('month', cs.cohort_month, DATE '2018-08-01')
),
period_activity AS (
    SELECT
        cohort_month,
        CAST(period_number AS INTEGER) AS period_number,
        COUNT(DISTINCT customer_unique_id) AS active_buyers,
        SUM(order_gmv) AS cohort_gmv
    FROM cohort_activity
    WHERE period_number BETWEEN 0 AND 11
    GROUP BY cohort_month, period_number
)
SELECT
    g.cohort_month,
    g.period_number,
    g.cohort_size,
    COALESCE(a.active_buyers, 0) AS active_buyers,
    100.0 * COALESCE(a.active_buyers, 0) / g.cohort_size AS retention_rate_pct,
    COALESCE(a.cohort_gmv, 0.0) AS cohort_gmv
FROM observable_grid AS g
LEFT JOIN period_activity AS a
    ON a.cohort_month = g.cohort_month
   AND a.period_number = g.period_number
ORDER BY g.cohort_month, g.period_number;
