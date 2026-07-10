-- ==============================================================================
-- ExperimentIQ — Session Behavioral Metrics
-- Purpose: Computes session-level metrics per variant for guardrail monitoring.
-- ==============================================================================

SELECT
    experiment_name,
    variant,
    total_sessions,
    unique_users,
    avg_session_duration_seconds AS avg_session_duration,
    median_session_duration_seconds AS median_session_duration,
    p75_duration_seconds AS p75_session_duration,
    avg_pages_per_session,
    bounce_rate,
    bounced_sessions,
    sessions_per_user
FROM v_session_metrics
ORDER BY experiment_name, variant;
