-- ==============================================================================
-- ExperimentIQ — Channel Segmentation
-- Purpose: Conversion and acquisition metrics by channel per variant.
-- ==============================================================================

WITH channel_metrics AS (
    SELECT
        experiment_name,
        channel_name,
        variant,
        SUM(total_users) AS total_users,
        SUM(purchasers) AS purchasers,
        CASE 
            WHEN SUM(total_users) = 0 THEN 0 
            ELSE SUM(purchasers)::FLOAT / SUM(total_users) 
        END AS conversion_rate
    FROM v_segment_conversion
    GROUP BY experiment_name, channel_name, variant
),
revenue_metrics AS (
    SELECT
        u.channel_id,
        ac.channel_name,
        e.experiment_name,
        e.variant,
        SUM(o.order_value) AS total_revenue
    FROM experiments e
    JOIN users u ON e.user_id = u.user_id
    JOIN acquisition_channels ac ON u.channel_id = ac.channel_id
    LEFT JOIN orders o ON e.user_id = o.user_id AND o.payment_status = 'completed' AND o.is_refund = FALSE
    WHERE e.is_holdout = FALSE
    GROUP BY u.channel_id, ac.channel_name, e.experiment_name, e.variant
)
SELECT
    c.experiment_name,
    c.channel_name,
    c.variant,
    c.total_users,
    c.purchasers,
    c.conversion_rate,
    COALESCE(r.total_revenue, 0) AS total_revenue,
    CASE
        WHEN c.total_users = 0 THEN 0
        ELSE COALESCE(r.total_revenue, 0) / c.total_users
    END AS revenue_per_visitor,
    RANK() OVER (PARTITION BY c.experiment_name, c.variant ORDER BY c.conversion_rate DESC) AS cr_rank
FROM channel_metrics c
LEFT JOIN revenue_metrics r 
    ON c.experiment_name = r.experiment_name 
   AND c.channel_name = r.channel_name 
   AND c.variant = r.variant
ORDER BY c.experiment_name, c.variant, c.conversion_rate DESC;
