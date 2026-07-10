-- ==============================================================================
-- ExperimentIQ — Completeness Check
-- Purpose: Data completeness checks across core tables.
-- ==============================================================================

SELECT
    'users' AS table_name,
    COUNT(*) AS row_count,
    COUNT(*) FILTER (WHERE user_id IS NULL OR signup_date IS NULL OR country_id IS NULL) AS null_count_key_columns,
    CASE WHEN COUNT(*) = 0 THEN 0 ELSE 100.0 - (COUNT(*) FILTER (WHERE user_id IS NULL OR signup_date IS NULL OR country_id IS NULL)::FLOAT / COUNT(*) * 100) END AS completeness_pct
FROM users
UNION ALL
SELECT
    'experiments' AS table_name,
    COUNT(*) AS row_count,
    COUNT(*) FILTER (WHERE experiment_id IS NULL OR user_id IS NULL OR variant IS NULL) AS null_count_key_columns,
    CASE WHEN COUNT(*) = 0 THEN 0 ELSE 100.0 - (COUNT(*) FILTER (WHERE experiment_id IS NULL OR user_id IS NULL OR variant IS NULL)::FLOAT / COUNT(*) * 100) END AS completeness_pct
FROM experiments
UNION ALL
SELECT
    'sessions' AS table_name,
    COUNT(*) AS row_count,
    COUNT(*) FILTER (WHERE session_id IS NULL OR user_id IS NULL OR session_start IS NULL) AS null_count_key_columns,
    CASE WHEN COUNT(*) = 0 THEN 0 ELSE 100.0 - (COUNT(*) FILTER (WHERE session_id IS NULL OR user_id IS NULL OR session_start IS NULL)::FLOAT / COUNT(*) * 100) END AS completeness_pct
FROM sessions
UNION ALL
SELECT
    'events' AS table_name,
    COUNT(*) AS row_count,
    COUNT(*) FILTER (WHERE event_id IS NULL OR session_id IS NULL OR event_type_id IS NULL) AS null_count_key_columns,
    CASE WHEN COUNT(*) = 0 THEN 0 ELSE 100.0 - (COUNT(*) FILTER (WHERE event_id IS NULL OR session_id IS NULL OR event_type_id IS NULL)::FLOAT / COUNT(*) * 100) END AS completeness_pct
FROM events
UNION ALL
SELECT
    'orders' AS table_name,
    COUNT(*) AS row_count,
    COUNT(*) FILTER (WHERE order_id IS NULL OR user_id IS NULL OR order_value IS NULL) AS null_count_key_columns,
    CASE WHEN COUNT(*) = 0 THEN 0 ELSE 100.0 - (COUNT(*) FILTER (WHERE order_id IS NULL OR user_id IS NULL OR order_value IS NULL)::FLOAT / COUNT(*) * 100) END AS completeness_pct
FROM orders;
