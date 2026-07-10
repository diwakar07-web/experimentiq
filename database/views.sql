-- ==============================================================================
-- ExperimentIQ — SQL Views & Materialized Views
-- Version: 1.0
-- Execution Order: Run AFTER indexes.sql
--
-- Design Principles:
--   - Views expose the analytical layer; Python never queries raw tables directly
--     for analytics (only for ingestion validation).
--   - Materialized views cache heavy aggregations for dashboard performance.
--   - Every view has a descriptive comment documenting its purpose and consumers.
--   - Views use CTEs for readability.
--   - No statistical calculations in SQL (statistics are Python's responsibility).
-- ==============================================================================

-- ==============================================================================
-- SECTION 1: REGULAR VIEWS
-- Updated in real-time — always reflect current database state.
-- ==============================================================================

-- ------------------------------------------------------------------------------
-- v_experiment_summary
-- Per-variant summary of users, purchasers, and revenue.
-- Primary consumer: Statistical Engine, Recommendation Engine, Executive Dashboard.
-- ------------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_experiment_summary AS
WITH experiment_users AS (
    -- All non-holdout users with their variant assignment
    SELECT
        e.user_id,
        e.experiment_name,
        e.variant,
        e.assignment_timestamp,
        DATE(e.assignment_timestamp) AS assignment_date
    FROM experiments e
    WHERE e.is_holdout = FALSE
),
user_purchases AS (
    -- One row per user; whether they made a purchase and their total revenue
    SELECT
        o.user_id,
        COUNT(DISTINCT o.order_id)                          AS total_orders,
        SUM(o.order_value)                                  AS total_revenue,
        MAX(o.order_timestamp)                              AS last_purchase_timestamp,
        BOOL_OR(NOT o.is_refund AND o.payment_status = 'completed') AS has_purchase
    FROM orders o
    WHERE o.payment_status = 'completed'
      AND o.is_refund = FALSE
    GROUP BY o.user_id
)
SELECT
    eu.experiment_name,
    eu.variant,
    COUNT(DISTINCT eu.user_id)                              AS total_users,
    COUNT(DISTINCT up.user_id) FILTER (WHERE up.has_purchase)   AS purchasers,
    COALESCE(SUM(up.total_revenue), 0)                      AS total_revenue,
    COALESCE(SUM(up.total_orders), 0)                       AS total_orders,
    -- Conversion rate (avoids division by zero)
    CASE
        WHEN COUNT(DISTINCT eu.user_id) = 0 THEN 0
        ELSE COUNT(DISTINCT up.user_id) FILTER (WHERE up.has_purchase)::FLOAT
             / COUNT(DISTINCT eu.user_id)
    END                                                      AS conversion_rate,
    -- Revenue per visitor
    CASE
        WHEN COUNT(DISTINCT eu.user_id) = 0 THEN 0
        ELSE COALESCE(SUM(up.total_revenue), 0)
             / COUNT(DISTINCT eu.user_id)
    END                                                      AS revenue_per_visitor,
    -- Average order value
    CASE
        WHEN COALESCE(SUM(up.total_orders), 0) = 0 THEN 0
        ELSE COALESCE(SUM(up.total_revenue), 0)
             / SUM(up.total_orders)
    END                                                      AS average_order_value,
    MIN(eu.assignment_timestamp)                             AS experiment_start,
    MAX(eu.assignment_timestamp)                             AS experiment_end
FROM experiment_users eu
LEFT JOIN user_purchases up ON eu.user_id = up.user_id
GROUP BY eu.experiment_name, eu.variant;

COMMENT ON VIEW v_experiment_summary IS
    'Per-variant aggregate: total users, purchasers, revenue, conversion rate, RPV, AOV.
     Primary input for statistical hypothesis testing.
     Consumers: StatisticalEngine, RecommendationEngine, ExecutiveDashboard.';

-- ------------------------------------------------------------------------------
-- v_daily_metrics
-- Daily conversion and revenue metrics by experiment variant.
-- Consumer: Conversion Dashboard, Time-Series Charts, Monitoring.
-- ------------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_daily_metrics AS
WITH daily_users AS (
    -- Count users assigned each day by variant
    SELECT
        DATE(e.assignment_timestamp)    AS metric_date,
        e.experiment_name,
        e.variant,
        COUNT(DISTINCT e.user_id)       AS users_assigned
    FROM experiments e
    WHERE e.is_holdout = FALSE
    GROUP BY DATE(e.assignment_timestamp), e.experiment_name, e.variant
),
daily_orders AS (
    -- Orders and revenue by date and user's variant
    SELECT
        DATE(o.order_timestamp)         AS metric_date,
        e.experiment_name,
        e.variant,
        COUNT(DISTINCT o.user_id)       AS purchasing_users,
        COUNT(DISTINCT o.order_id)      AS order_count,
        SUM(o.order_value)              AS daily_revenue
    FROM orders o
    JOIN experiments e ON o.user_id = e.user_id
    WHERE o.payment_status = 'completed'
      AND o.is_refund = FALSE
      AND e.is_holdout = FALSE
    GROUP BY DATE(o.order_timestamp), e.experiment_name, e.variant
)
SELECT
    du.metric_date,
    du.experiment_name,
    du.variant,
    du.users_assigned,
    COALESCE(dord.purchasing_users, 0)          AS purchasing_users,
    COALESCE(dord.order_count, 0)               AS order_count,
    COALESCE(dord.daily_revenue, 0)             AS daily_revenue,
    CASE
        WHEN du.users_assigned = 0 THEN 0
        ELSE COALESCE(dord.purchasing_users, 0)::FLOAT / du.users_assigned
    END                                         AS daily_conversion_rate,
    CASE
        WHEN du.users_assigned = 0 THEN 0
        ELSE COALESCE(dord.daily_revenue, 0) / du.users_assigned
    END                                         AS daily_revenue_per_visitor,
    -- Cumulative users (window function)
    SUM(du.users_assigned) OVER (
        PARTITION BY du.experiment_name, du.variant
        ORDER BY du.metric_date
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    )                                           AS cumulative_users,
    -- Cumulative purchases (window function)
    SUM(COALESCE(dord.purchasing_users, 0)) OVER (
        PARTITION BY du.experiment_name, du.variant
        ORDER BY du.metric_date
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    )                                           AS cumulative_purchasers,
    -- 7-day rolling conversion rate
    SUM(COALESCE(dord.purchasing_users, 0)) OVER (
        PARTITION BY du.experiment_name, du.variant
        ORDER BY du.metric_date
        ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    )::FLOAT
    / NULLIF(SUM(du.users_assigned) OVER (
        PARTITION BY du.experiment_name, du.variant
        ORDER BY du.metric_date
        ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    ), 0)                                       AS rolling_7d_conversion_rate
FROM daily_users du
LEFT JOIN daily_orders dord
    ON du.metric_date = dord.metric_date
   AND du.experiment_name = dord.experiment_name
   AND du.variant = dord.variant
ORDER BY du.experiment_name, du.variant, du.metric_date;

COMMENT ON VIEW v_daily_metrics IS
    'Daily and cumulative conversion/revenue metrics by experiment variant.
     Includes 7-day rolling conversion rate.
     Consumers: ConversionDashboard, MonitoringDashboard, AnalyticsEngine.';

-- ------------------------------------------------------------------------------
-- v_funnel_steps
-- Funnel step completion counts by variant and experiment.
-- Consumer: Funnel Dashboard, FunnelAnalyzer.
-- ------------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_funnel_steps AS
WITH experiment_users AS (
    SELECT user_id, experiment_name, variant
    FROM experiments
    WHERE is_holdout = FALSE
),
funnel_events AS (
    -- For each session, determine the deepest funnel step reached
    SELECT
        ev.session_id,
        ev.user_id,
        et.event_name,
        et.funnel_step,
        ev.event_timestamp
    FROM events ev
    JOIN event_types et ON ev.event_type_id = et.event_type_id
    WHERE et.funnel_step IS NOT NULL
),
user_funnel AS (
    -- Max funnel step reached per user per experiment
    SELECT
        eu.user_id,
        eu.experiment_name,
        eu.variant,
        -- Individual step flags (BOOL: did the user reach this step?)
        BOOL_OR(fe.event_name = 'page_view')         AS reached_landing,
        BOOL_OR(fe.event_name = 'product_view')      AS reached_product,
        BOOL_OR(fe.event_name = 'add_to_cart')       AS reached_cart,
        BOOL_OR(fe.event_name = 'checkout_start')    AS reached_checkout,
        BOOL_OR(fe.event_name = 'purchase')          AS reached_purchase
    FROM experiment_users eu
    LEFT JOIN sessions s ON eu.user_id = s.user_id
    LEFT JOIN funnel_events fe ON s.session_id = fe.session_id
    GROUP BY eu.user_id, eu.experiment_name, eu.variant
)
SELECT
    uf.experiment_name,
    uf.variant,
    COUNT(DISTINCT uf.user_id)                              AS total_users,
    COUNT(DISTINCT uf.user_id) FILTER (WHERE uf.reached_landing)    AS landing_users,
    COUNT(DISTINCT uf.user_id) FILTER (WHERE uf.reached_product)    AS product_users,
    COUNT(DISTINCT uf.user_id) FILTER (WHERE uf.reached_cart)       AS cart_users,
    COUNT(DISTINCT uf.user_id) FILTER (WHERE uf.reached_checkout)   AS checkout_users,
    COUNT(DISTINCT uf.user_id) FILTER (WHERE uf.reached_purchase)   AS purchase_users,
    -- Step-over-step drop-off rates
    CASE WHEN COUNT(DISTINCT uf.user_id) FILTER (WHERE uf.reached_landing) = 0 THEN 0
         ELSE COUNT(DISTINCT uf.user_id) FILTER (WHERE uf.reached_product)::FLOAT
              / COUNT(DISTINCT uf.user_id) FILTER (WHERE uf.reached_landing)
    END                                                      AS landing_to_product_rate,
    CASE WHEN COUNT(DISTINCT uf.user_id) FILTER (WHERE uf.reached_product) = 0 THEN 0
         ELSE COUNT(DISTINCT uf.user_id) FILTER (WHERE uf.reached_cart)::FLOAT
              / COUNT(DISTINCT uf.user_id) FILTER (WHERE uf.reached_product)
    END                                                      AS product_to_cart_rate,
    CASE WHEN COUNT(DISTINCT uf.user_id) FILTER (WHERE uf.reached_cart) = 0 THEN 0
         ELSE COUNT(DISTINCT uf.user_id) FILTER (WHERE uf.reached_checkout)::FLOAT
              / COUNT(DISTINCT uf.user_id) FILTER (WHERE uf.reached_cart)
    END                                                      AS cart_to_checkout_rate,
    CASE WHEN COUNT(DISTINCT uf.user_id) FILTER (WHERE uf.reached_checkout) = 0 THEN 0
         ELSE COUNT(DISTINCT uf.user_id) FILTER (WHERE uf.reached_purchase)::FLOAT
              / COUNT(DISTINCT uf.user_id) FILTER (WHERE uf.reached_checkout)
    END                                                      AS checkout_to_purchase_rate,
    -- Overall funnel completion rate
    CASE WHEN COUNT(DISTINCT uf.user_id) = 0 THEN 0
         ELSE COUNT(DISTINCT uf.user_id) FILTER (WHERE uf.reached_purchase)::FLOAT
              / COUNT(DISTINCT uf.user_id)
    END                                                      AS overall_funnel_rate
FROM user_funnel uf
GROUP BY uf.experiment_name, uf.variant;

COMMENT ON VIEW v_funnel_steps IS
    'Funnel step completion counts and step-over-step conversion rates by variant.
     Consumers: FunnelDashboard, FunnelAnalyzer.';

-- ------------------------------------------------------------------------------
-- v_session_metrics
-- Session-level behaviour metrics by experiment variant.
-- Consumer: Session Dashboard, Guardrail Monitoring.
-- ------------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_session_metrics AS
WITH experiment_sessions AS (
    SELECT
        s.session_id,
        s.user_id,
        s.duration_seconds,
        s.page_count,
        s.is_bounce,
        e.experiment_name,
        e.variant
    FROM sessions s
    JOIN experiments e ON s.user_id = e.user_id
    WHERE e.is_holdout = FALSE
)
SELECT
    es.experiment_name,
    es.variant,
    COUNT(DISTINCT es.session_id)                                   AS total_sessions,
    COUNT(DISTINCT es.user_id)                                      AS unique_users,
    ROUND(AVG(es.duration_seconds)::NUMERIC, 2)                     AS avg_session_duration_seconds,
    ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY es.duration_seconds)::NUMERIC, 2)
                                                                    AS median_session_duration_seconds,
    ROUND(AVG(es.page_count)::NUMERIC, 2)                           AS avg_pages_per_session,
    ROUND(
        COUNT(DISTINCT es.session_id) FILTER (WHERE es.is_bounce)::NUMERIC
        / NULLIF(COUNT(DISTINCT es.session_id), 0), 4
    )                                                               AS bounce_rate,
    COUNT(DISTINCT es.session_id) FILTER (WHERE es.is_bounce)       AS bounced_sessions,
    ROUND(
        COUNT(DISTINCT es.user_id)::NUMERIC
        / NULLIF(COUNT(DISTINCT es.session_id), 0), 3
    )                                                               AS sessions_per_user,
    -- Percentile distribution of session duration
    PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY es.duration_seconds) AS p25_duration_seconds,
    PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY es.duration_seconds) AS p75_duration_seconds,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY es.duration_seconds) AS p95_duration_seconds
FROM experiment_sessions es
GROUP BY es.experiment_name, es.variant;

COMMENT ON VIEW v_session_metrics IS
    'Session engagement metrics per experiment variant.
     Includes bounce rate, avg duration, pages per session, percentiles.
     Consumers: SessionDashboard, GuardrailMonitoring, SegmentAnalyzer.';

-- ------------------------------------------------------------------------------
-- v_segment_conversion
-- Conversion rates segmented by device, country, channel, and customer type.
-- Consumer: Segmentation Dashboard, SegmentAnalyzer.
-- ------------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_segment_conversion AS
WITH base AS (
    SELECT
        e.user_id,
        e.experiment_name,
        e.variant,
        d.device_type,
        c.country_name,
        c.country_code,
        r.region_name,
        ac.channel_name,
        u.customer_type
    FROM experiments e
    JOIN users u       ON e.user_id = u.user_id
    JOIN devices d     ON u.device_id = d.device_id
    JOIN countries c   ON u.country_id = c.country_id
    JOIN regions r     ON c.region_id = r.region_id
    JOIN acquisition_channels ac ON u.channel_id = ac.channel_id
    WHERE e.is_holdout = FALSE
),
purchases AS (
    SELECT DISTINCT user_id
    FROM orders
    WHERE payment_status = 'completed'
      AND is_refund = FALSE
)
SELECT
    b.experiment_name,
    b.variant,
    b.device_type,
    b.country_name,
    b.country_code,
    b.region_name,
    b.channel_name,
    b.customer_type,
    COUNT(DISTINCT b.user_id)                                   AS total_users,
    COUNT(DISTINCT b.user_id) FILTER (WHERE p.user_id IS NOT NULL) AS purchasers,
    CASE
        WHEN COUNT(DISTINCT b.user_id) = 0 THEN 0
        ELSE COUNT(DISTINCT b.user_id) FILTER (WHERE p.user_id IS NOT NULL)::FLOAT
             / COUNT(DISTINCT b.user_id)
    END                                                         AS conversion_rate
FROM base b
LEFT JOIN purchases p ON b.user_id = p.user_id
GROUP BY
    b.experiment_name,
    b.variant,
    b.device_type,
    b.country_name,
    b.country_code,
    b.region_name,
    b.channel_name,
    b.customer_type;

COMMENT ON VIEW v_segment_conversion IS
    'Conversion rates broken down by device, country, region, channel, and customer type.
     Consumers: SegmentationDashboard, SegmentAnalyzer.';

-- ------------------------------------------------------------------------------
-- v_revenue_summary
-- Revenue metrics by variant: total revenue, RPV, AOV, refund rate.
-- Consumer: Revenue Dashboard, ReportBuilder.
-- ------------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_revenue_summary AS
WITH variant_orders AS (
    SELECT
        o.order_id,
        o.user_id,
        o.order_value,
        o.is_refund,
        o.payment_status,
        o.payment_method,
        e.experiment_name,
        e.variant
    FROM orders o
    JOIN experiments e ON o.user_id = e.user_id
    WHERE e.is_holdout = FALSE
),
variant_users AS (
    SELECT experiment_name, variant, COUNT(DISTINCT user_id) AS total_users
    FROM experiments
    WHERE is_holdout = FALSE
    GROUP BY experiment_name, variant
)
SELECT
    vo.experiment_name,
    vo.variant,
    vu.total_users,
    SUM(vo.order_value) FILTER (WHERE NOT vo.is_refund AND vo.payment_status = 'completed')
                                                            AS gross_revenue,
    SUM(vo.order_value) FILTER (WHERE vo.is_refund)         AS refunded_revenue,
    SUM(vo.order_value) FILTER (WHERE NOT vo.is_refund AND vo.payment_status = 'completed')
    - COALESCE(SUM(vo.order_value) FILTER (WHERE vo.is_refund), 0)
                                                            AS net_revenue,
    COUNT(DISTINCT vo.order_id) FILTER (WHERE NOT vo.is_refund AND vo.payment_status = 'completed')
                                                            AS completed_orders,
    COUNT(DISTINCT vo.order_id) FILTER (WHERE vo.is_refund) AS refunded_orders,
    COUNT(DISTINCT vo.order_id) FILTER (WHERE vo.payment_status = 'failed')
                                                            AS failed_orders,
    -- Revenue per visitor (total users in variant, not just buyers)
    CASE WHEN vu.total_users = 0 THEN 0
         ELSE SUM(vo.order_value) FILTER (WHERE NOT vo.is_refund AND vo.payment_status = 'completed')
              / vu.total_users
    END                                                     AS revenue_per_visitor,
    -- Average order value (over completed orders only)
    CASE
        WHEN COUNT(DISTINCT vo.order_id) FILTER (WHERE NOT vo.is_refund AND vo.payment_status = 'completed') = 0
        THEN 0
        ELSE SUM(vo.order_value) FILTER (WHERE NOT vo.is_refund AND vo.payment_status = 'completed')
             / COUNT(DISTINCT vo.order_id) FILTER (WHERE NOT vo.is_refund AND vo.payment_status = 'completed')
    END                                                     AS average_order_value,
    -- Refund rate
    CASE
        WHEN COUNT(DISTINCT vo.order_id) FILTER (WHERE NOT vo.is_refund AND vo.payment_status = 'completed') = 0
        THEN 0
        ELSE COUNT(DISTINCT vo.order_id) FILTER (WHERE vo.is_refund)::FLOAT
             / COUNT(DISTINCT vo.order_id) FILTER (WHERE NOT vo.is_refund AND vo.payment_status = 'completed')
    END                                                     AS refund_rate
FROM variant_orders vo
JOIN variant_users vu
    ON vo.experiment_name = vu.experiment_name
   AND vo.variant = vu.variant
GROUP BY vo.experiment_name, vo.variant, vu.total_users;

COMMENT ON VIEW v_revenue_summary IS
    'Revenue summary per variant: gross/net revenue, RPV, AOV, refund rate.
     Consumers: RevenueDashboard, ReportBuilder, RecommendationEngine.';

-- ==============================================================================
-- SECTION 2: MATERIALIZED VIEWS
-- Pre-computed for dashboard performance. Must be refreshed after data load.
-- ==============================================================================

-- ------------------------------------------------------------------------------
-- mv_user_experiment_summary
-- Per-user experiment result summary. Heavy join cached for dashboard queries.
-- Refresh: After each data load and analytics pipeline run.
-- ------------------------------------------------------------------------------
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_user_experiment_summary AS
WITH user_revenue AS (
    SELECT
        user_id,
        SUM(order_value) FILTER (WHERE payment_status = 'completed' AND is_refund = FALSE)
                                    AS total_revenue,
        COUNT(order_id) FILTER (WHERE payment_status = 'completed' AND is_refund = FALSE)
                                    AS order_count,
        MAX(order_timestamp)         AS last_purchase_date,
        BOOL_OR(payment_status = 'completed' AND is_refund = FALSE)
                                    AS made_purchase
    FROM orders
    GROUP BY user_id
),
user_sessions AS (
    SELECT
        user_id,
        COUNT(session_id)            AS session_count,
        SUM(duration_seconds)        AS total_session_seconds,
        AVG(duration_seconds)        AS avg_session_seconds,
        AVG(page_count)              AS avg_page_count,
        SUM(CASE WHEN is_bounce THEN 1 ELSE 0 END) AS bounce_count
    FROM sessions
    GROUP BY user_id
)
SELECT
    e.user_id,
    e.experiment_name,
    e.variant,
    e.assignment_timestamp,
    DATE(e.assignment_timestamp)                    AS assignment_date,
    u.customer_type,
    d.device_type,
    c.country_name,
    c.country_code,
    r.region_name,
    ac.channel_name,
    COALESCE(ur.made_purchase, FALSE)               AS made_purchase,
    COALESCE(ur.order_count, 0)                     AS order_count,
    COALESCE(ur.total_revenue, 0)                   AS total_revenue,
    ur.last_purchase_date,
    COALESCE(us.session_count, 0)                   AS session_count,
    COALESCE(us.avg_session_seconds, 0)             AS avg_session_duration_seconds,
    COALESCE(us.avg_page_count, 0)                  AS avg_page_count,
    CASE
        WHEN COALESCE(us.session_count, 0) = 0 THEN 0
        ELSE COALESCE(us.bounce_count, 0)::FLOAT / us.session_count
    END                                             AS bounce_rate
FROM experiments e
JOIN users u        ON e.user_id = u.user_id
JOIN devices d      ON u.device_id = d.device_id
JOIN countries c    ON u.country_id = c.country_id
JOIN regions r      ON c.region_id = r.region_id
JOIN acquisition_channels ac ON u.channel_id = ac.channel_id
LEFT JOIN user_revenue ur  ON e.user_id = ur.user_id
LEFT JOIN user_sessions us ON e.user_id = us.user_id
WHERE e.is_holdout = FALSE
WITH DATA;

-- Index on the materialized view for fast dashboard queries
CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_user_experiment_summary_pk
    ON mv_user_experiment_summary (user_id, experiment_name);

CREATE INDEX IF NOT EXISTS idx_mv_user_experiment_summary_variant
    ON mv_user_experiment_summary (experiment_name, variant);

CREATE INDEX IF NOT EXISTS idx_mv_user_experiment_summary_device
    ON mv_user_experiment_summary (device_type, variant);

CREATE INDEX IF NOT EXISTS idx_mv_user_experiment_summary_country
    ON mv_user_experiment_summary (country_code, variant);

COMMENT ON MATERIALIZED VIEW mv_user_experiment_summary IS
    'Per-user experiment result with all dimension attributes.
     Refresh after each pipeline run: REFRESH MATERIALIZED VIEW CONCURRENTLY mv_user_experiment_summary.
     Consumers: SegmentationDashboard, StatisticalEngine (bulk reads), AnalyticsEngine.';

-- ------------------------------------------------------------------------------
-- mv_daily_conversion
-- Pre-aggregated daily conversion for dashboard time-series charts.
-- Refresh: After each pipeline run.
-- ------------------------------------------------------------------------------
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_daily_conversion AS
SELECT
    metric_date,
    experiment_name,
    variant,
    users_assigned,
    purchasing_users,
    order_count,
    daily_revenue,
    daily_conversion_rate,
    daily_revenue_per_visitor,
    cumulative_users,
    cumulative_purchasers,
    rolling_7d_conversion_rate,
    -- Cumulative conversion rate
    CASE
        WHEN cumulative_users = 0 THEN 0
        ELSE cumulative_purchasers::FLOAT / cumulative_users
    END AS cumulative_conversion_rate
FROM v_daily_metrics
WITH DATA;

CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_daily_conversion_pk
    ON mv_daily_conversion (experiment_name, variant, metric_date);

CREATE INDEX IF NOT EXISTS idx_mv_daily_conversion_date
    ON mv_daily_conversion (metric_date);

COMMENT ON MATERIALIZED VIEW mv_daily_conversion IS
    'Pre-aggregated daily conversion metrics for dashboard time-series charts.
     Refresh after each pipeline run.
     Consumers: ConversionDashboard, MonitoringDashboard.';

-- ==============================================================================
-- SECTION 3: HELPER FUNCTION — Materialized View Refresh
-- ==============================================================================

CREATE OR REPLACE FUNCTION refresh_all_materialized_views()
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE NOTICE 'Refreshing materialized view: mv_user_experiment_summary';
    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_user_experiment_summary;

    RAISE NOTICE 'Refreshing materialized view: mv_daily_conversion';
    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_daily_conversion;

    RAISE NOTICE 'All materialized views refreshed successfully.';
END;
$$;

COMMENT ON FUNCTION refresh_all_materialized_views() IS
    'Refreshes all ExperimentIQ materialized views concurrently.
     Call after each pipeline run: SELECT refresh_all_materialized_views();';
