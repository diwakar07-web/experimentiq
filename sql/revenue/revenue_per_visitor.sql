-- ==============================================================================
-- ExperimentIQ — Revenue Per Visitor
-- Purpose: RPV analysis with percentiles and distribution per variant.
-- ==============================================================================

WITH user_revenue AS (
    SELECT
        e.experiment_name,
        e.variant,
        o.user_id,
        SUM(o.order_value) AS total_user_revenue,
        COUNT(o.order_id) AS user_order_count
    FROM experiments e
    JOIN orders o ON e.user_id = o.user_id
    WHERE e.is_holdout = FALSE
      AND o.payment_status = 'completed'
      AND o.is_refund = FALSE
    GROUP BY e.experiment_name, e.variant, o.user_id
),
revenue_percentiles AS (
    SELECT
        experiment_name,
        variant,
        PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY total_user_revenue) AS p25_order_value,
        PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY total_user_revenue) AS median_order_value,
        PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY total_user_revenue) AS p75_order_value,
        PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY total_user_revenue) AS p95_order_value
    FROM user_revenue
    GROUP BY experiment_name, variant
)
SELECT
    s.experiment_name,
    s.variant,
    s.total_users,
    s.gross_revenue AS total_revenue,
    s.revenue_per_visitor,
    s.average_order_value AS avg_order_value,
    p.median_order_value,
    p.p25_order_value,
    p.p75_order_value,
    p.p95_order_value,
    s.refund_rate
FROM v_revenue_summary s
LEFT JOIN revenue_percentiles p 
    ON s.experiment_name = p.experiment_name 
   AND s.variant = p.variant
ORDER BY s.experiment_name, s.variant;
