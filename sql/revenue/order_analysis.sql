-- ==============================================================================
-- ExperimentIQ — Order Analysis
-- Purpose: Detailed order-level analysis including payment methods.
-- ==============================================================================

WITH order_buckets AS (
    SELECT
        e.experiment_name,
        e.variant,
        o.order_id,
        o.order_value,
        o.payment_method,
        o.is_refund,
        DATE(o.order_timestamp) AS order_date,
        CASE
            WHEN o.order_value < 20 THEN '1. Under $20'
            WHEN o.order_value < 50 THEN '2. $20 - $49.99'
            WHEN o.order_value < 100 THEN '3. $50 - $99.99'
            WHEN o.order_value < 200 THEN '4. $100 - $199.99'
            ELSE '5. $200+'
        END AS order_value_bucket
    FROM orders o
    JOIN experiments e ON o.user_id = e.user_id
    WHERE o.payment_status = 'completed'
      AND e.is_holdout = FALSE
)
SELECT
    experiment_name,
    variant,
    order_date,
    payment_method,
    order_value_bucket,
    COUNT(order_id) AS total_orders,
    SUM(order_value) AS total_revenue,
    SUM(CASE WHEN is_refund THEN 1 ELSE 0 END) AS refunded_orders,
    SUM(CASE WHEN is_refund THEN order_value ELSE 0 END) AS refunded_revenue
FROM order_buckets
GROUP BY 
    experiment_name,
    variant,
    order_date,
    payment_method,
    order_value_bucket
ORDER BY 
    experiment_name,
    variant,
    order_date,
    payment_method,
    order_value_bucket;
