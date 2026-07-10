-- ==============================================================================
-- ExperimentIQ — Conversion Metrics
-- Purpose: Computes per-variant conversion metrics for the primary hypothesis test.
-- ==============================================================================

WITH base_metrics AS (
    SELECT
        experiment_name,
        variant,
        total_users,
        purchasers,
        conversion_rate,
        total_revenue,
        total_orders
    FROM v_experiment_summary
),
control_metrics AS (
    SELECT
        experiment_name,
        conversion_rate AS control_cr
    FROM base_metrics
    WHERE variant = 'control'
)
SELECT
    b.experiment_name,
    b.variant,
    b.total_users,
    b.purchasers,
    b.conversion_rate,
    b.total_revenue,
    b.total_orders,
    CASE 
        WHEN b.variant = 'control' THEN 0
        ELSE b.conversion_rate - c.control_cr 
    END AS lift_absolute,
    CASE 
        WHEN b.variant = 'control' THEN 0
        WHEN c.control_cr = 0 THEN NULL
        ELSE (b.conversion_rate - c.control_cr) / c.control_cr 
    END AS lift_relative,
    NULL::FLOAT AS confidence_level_placeholder -- Filled by Python stats engine
FROM base_metrics b
LEFT JOIN control_metrics c ON b.experiment_name = c.experiment_name
ORDER BY b.experiment_name, b.variant;
