-- ==============================================================================
-- ExperimentIQ — Daily Metrics
-- Purpose: Time-series query for daily experiment metrics and rolling averages.
-- ==============================================================================

SELECT
    metric_date,
    experiment_name,
    variant,
    users_assigned AS daily_users,
    purchasing_users AS daily_conversions,
    daily_conversion_rate,
    cumulative_users,
    cumulative_purchasers AS cumulative_conversions,
    cumulative_conversion_rate,
    rolling_7d_conversion_rate,
    daily_revenue,
    SUM(daily_revenue) OVER (
        PARTITION BY experiment_name, variant 
        ORDER BY metric_date
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS cumulative_revenue,
    -- Day-over-day change in conversion rate
    daily_conversion_rate - LAG(daily_conversion_rate, 1) OVER (
        PARTITION BY experiment_name, variant 
        ORDER BY metric_date
    ) AS dod_conversion_change
FROM mv_daily_conversion
ORDER BY experiment_name, variant, metric_date;
