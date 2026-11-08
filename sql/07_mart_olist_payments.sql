-- mart_olist_payments: one row per payment type over payments of delivered orders.
-- Payment value is a different measure from GMV (price + freight): it reflects what was charged per payment record,
-- and one order can be paid with several records and types (e.g. card + voucher), so orders_using_type is not additive.
CREATE OR REPLACE TABLE mart_olist_payments AS
WITH delivered_payments AS (
    SELECT
        p.order_id,
        p.payment_type,
        p.payment_installments,
        p.payment_value
    FROM raw_order_payments AS p
    INNER JOIN mart_order_fulfillment AS f
        ON f.order_id = p.order_id
)
SELECT
    payment_type,
    COUNT(*) AS payment_records,
    COUNT(DISTINCT order_id) AS orders_using_type,
    SUM(payment_value) AS payment_value,
    SUM(payment_value) / SUM(SUM(payment_value)) OVER () AS payment_value_share,
    AVG(CAST(payment_installments AS DOUBLE)) AS mean_installments
FROM delivered_payments
GROUP BY payment_type
ORDER BY payment_value DESC;
