-- ==============================================================================
-- ExperimentIQ — Data Quality Monitoring
-- Purpose: Data quality monitoring queries (completeness, orphans).
-- ==============================================================================

WITH events_missing_experiment AS (
    SELECT COUNT(*) AS events_without_experiment
    FROM events
    WHERE experiment_id IS NULL
),
orphan_sessions AS (
    SELECT COUNT(s.session_id) AS orphan_sessions_count
    FROM sessions s
    LEFT JOIN events e ON s.session_id = e.session_id
    WHERE e.event_id IS NULL
),
duplicate_experiments AS (
    SELECT COUNT(*) AS duplicate_experiment_assignments
    FROM (
        SELECT user_id, experiment_name
        FROM experiments
        GROUP BY user_id, experiment_name
        HAVING COUNT(*) > 1
    ) sub
),
revenue_sanity AS (
    SELECT 
        MIN(order_value) AS min_revenue,
        MAX(order_value) AS max_revenue,
        AVG(order_value) AS avg_revenue,
        COUNT(*) FILTER (WHERE order_value > 1000) AS extreme_outliers_count
    FROM orders
    WHERE payment_status = 'completed' AND is_refund = FALSE
)
SELECT 
    (SELECT events_without_experiment FROM events_missing_experiment) AS events_without_experiment,
    (SELECT orphan_sessions_count FROM orphan_sessions) AS orphan_sessions_count,
    (SELECT duplicate_experiment_assignments FROM duplicate_experiments) AS duplicate_experiment_assignments,
    r.min_revenue,
    r.max_revenue,
    r.avg_revenue,
    r.extreme_outliers_count
FROM revenue_sanity r;
