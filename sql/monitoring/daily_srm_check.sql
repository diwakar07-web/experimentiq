-- ==============================================================================
-- ExperimentIQ — Daily SRM Check
-- Purpose: Monitors whether variant split remains balanced over time.
-- ==============================================================================

WITH daily_counts AS (
    SELECT
        metric_date,
        experiment_name,
        SUM(CASE WHEN variant = 'control' THEN users_assigned ELSE 0 END) AS daily_control,
        SUM(CASE WHEN variant = 'variant' THEN users_assigned ELSE 0 END) AS daily_variant,
        SUM(users_assigned) AS daily_total,
        SUM(CASE WHEN variant = 'control' THEN cumulative_users ELSE 0 END) AS cumulative_control,
        SUM(CASE WHEN variant = 'variant' THEN cumulative_users ELSE 0 END) AS cumulative_variant,
        SUM(cumulative_users) AS cumulative_total
    FROM mv_daily_conversion
    GROUP BY metric_date, experiment_name
)
SELECT
    metric_date,
    experiment_name,
    0.50 AS expected_variant_fraction,
    CASE 
        WHEN daily_total = 0 THEN 0 
        ELSE daily_variant::FLOAT / daily_total 
    END AS actual_daily_variant_fraction,
    CASE 
        WHEN cumulative_total = 0 THEN 0 
        ELSE cumulative_variant::FLOAT / cumulative_total 
    END AS actual_cumulative_variant_fraction,
    daily_control AS daily_users_control,
    daily_variant AS daily_users_variant,
    cumulative_control,
    cumulative_variant,
    -- Simple threshold-based flag (Python handles statistical chi-square check)
    CASE 
        WHEN cumulative_total > 1000 AND ABS((cumulative_variant::FLOAT / cumulative_total) - 0.50) > 0.05 THEN TRUE
        ELSE FALSE
    END AS srm_warning_flag
FROM daily_counts
ORDER BY experiment_name, metric_date;
