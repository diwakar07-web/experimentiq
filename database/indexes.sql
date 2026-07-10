-- ==============================================================================
-- ExperimentIQ — Performance Index Definitions
-- Version: 1.0
-- Execution Order: Run AFTER schema.sql and constraints.sql
--
-- Index Strategy:
--   - Every FK column gets a basic B-tree index (PostgreSQL does NOT auto-index FKs).
--   - Frequently filtered columns (timestamps, variant, event_name) get indexes.
--   - Composite indexes target the most common analytical JOIN patterns.
--   - Partial indexes reduce index size for sparse columns.
--   - CONCURRENTLY is not used here as these run during init (no active connections).
--
-- Naming Convention:
--   idx_{table}_{column(s)}[_{type_suffix}]
-- ==============================================================================

-- ==============================================================================
-- SECTION 1: countries
-- ==============================================================================

CREATE INDEX IF NOT EXISTS idx_countries_region_id
    ON countries (region_id);

-- ==============================================================================
-- SECTION 2: users
-- ==============================================================================

-- FK support indexes
CREATE INDEX IF NOT EXISTS idx_users_country_id
    ON users (country_id);

CREATE INDEX IF NOT EXISTS idx_users_device_id
    ON users (device_id);

CREATE INDEX IF NOT EXISTS idx_users_browser_id
    ON users (browser_id);

CREATE INDEX IF NOT EXISTS idx_users_channel_id
    ON users (channel_id);

-- Analytical filters
CREATE INDEX IF NOT EXISTS idx_users_signup_date
    ON users (signup_date);

CREATE INDEX IF NOT EXISTS idx_users_customer_type
    ON users (customer_type);

-- Composite: country + device (common segmentation combination)
CREATE INDEX IF NOT EXISTS idx_users_country_device
    ON users (country_id, device_id);

-- Composite: channel + customer_type (acquisition analysis)
CREATE INDEX IF NOT EXISTS idx_users_channel_customer_type
    ON users (channel_id, customer_type);

-- ==============================================================================
-- SECTION 3: experiments
-- ==============================================================================

-- FK support
CREATE INDEX IF NOT EXISTS idx_experiments_user_id
    ON experiments (user_id);

-- High-frequency filter: variant lookup
CREATE INDEX IF NOT EXISTS idx_experiments_variant
    ON experiments (variant);

-- Assignment timestamp (for experiment monitoring)
CREATE INDEX IF NOT EXISTS idx_experiments_assignment_timestamp
    ON experiments (assignment_timestamp);

-- Composite: experiment analysis by variant + timestamp
CREATE INDEX IF NOT EXISTS idx_experiments_name_variant
    ON experiments (experiment_name, variant);

-- Composite: joining experiments to users by assignment date
CREATE INDEX IF NOT EXISTS idx_experiments_user_variant
    ON experiments (user_id, variant);

-- ==============================================================================
-- SECTION 4: sessions
-- ==============================================================================

-- FK support
CREATE INDEX IF NOT EXISTS idx_sessions_user_id
    ON sessions (user_id);

CREATE INDEX IF NOT EXISTS idx_sessions_device_id
    ON sessions (device_id);

CREATE INDEX IF NOT EXISTS idx_sessions_browser_id
    ON sessions (browser_id);

-- Temporal filtering (primary analytical axis)
CREATE INDEX IF NOT EXISTS idx_sessions_session_start
    ON sessions (session_start);

-- Date-level aggregation (used by daily_metrics queries)
CREATE INDEX IF NOT EXISTS idx_sessions_session_start_date
    ON sessions (CAST(session_start AT TIME ZONE 'UTC' AS DATE));

-- Bounce rate analysis (partial index — only bounced sessions)
CREATE INDEX IF NOT EXISTS idx_sessions_bounced
    ON sessions (user_id, session_start)
    WHERE is_bounce = TRUE;

-- ==============================================================================
-- SECTION 5: events
-- ==============================================================================

-- FK support
CREATE INDEX IF NOT EXISTS idx_events_session_id
    ON events (session_id);

CREATE INDEX IF NOT EXISTS idx_events_user_id
    ON events (user_id);

CREATE INDEX IF NOT EXISTS idx_events_experiment_id
    ON events (experiment_id)
    WHERE experiment_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_events_event_type_id
    ON events (event_type_id);

-- Temporal filtering (highest cardinality, most filtered column)
CREATE INDEX IF NOT EXISTS idx_events_event_timestamp
    ON events (event_timestamp);

-- Date-level partitioning proxy (daily aggregation queries)
CREATE INDEX IF NOT EXISTS idx_events_event_date
    ON events (CAST(event_timestamp AT TIME ZONE 'UTC' AS DATE));

-- Revenue events (partial index — only events with revenue)
CREATE INDEX IF NOT EXISTS idx_events_revenue_nonnull
    ON events (user_id, event_timestamp, revenue)
    WHERE revenue IS NOT NULL;

-- Mobile events (partial index)
CREATE INDEX IF NOT EXISTS idx_events_mobile
    ON events (user_id, event_timestamp)
    WHERE is_mobile = TRUE;

-- Composite: most common analytical query — events by experiment + type + date
CREATE INDEX IF NOT EXISTS idx_events_experiment_type_timestamp
    ON events (experiment_id, event_type_id, event_timestamp);

-- Composite: funnel analysis — session + event type
CREATE INDEX IF NOT EXISTS idx_events_session_event_type
    ON events (session_id, event_type_id);

-- Composite: user-level funnel — user + event type
CREATE INDEX IF NOT EXISTS idx_events_user_event_type_timestamp
    ON events (user_id, event_type_id, event_timestamp);

-- ==============================================================================
-- SECTION 6: orders
-- ==============================================================================

-- FK support
CREATE INDEX IF NOT EXISTS idx_orders_user_id
    ON orders (user_id);

CREATE INDEX IF NOT EXISTS idx_orders_session_id
    ON orders (session_id);

CREATE INDEX IF NOT EXISTS idx_orders_event_id
    ON orders (event_id)
    WHERE event_id IS NOT NULL;

-- Temporal filtering
CREATE INDEX IF NOT EXISTS idx_orders_order_timestamp
    ON orders (order_timestamp);

-- Revenue analysis
CREATE INDEX IF NOT EXISTS idx_orders_order_value
    ON orders (order_value);

-- Refund tracking (partial index)
CREATE INDEX IF NOT EXISTS idx_orders_refunded
    ON orders (user_id, order_timestamp)
    WHERE is_refund = TRUE;

-- Payment status filtering
CREATE INDEX IF NOT EXISTS idx_orders_payment_status
    ON orders (payment_status);

-- Composite: revenue by user + timestamp (RPV, AOV queries)
CREATE INDEX IF NOT EXISTS idx_orders_user_timestamp_value
    ON orders (user_id, order_timestamp, order_value);

-- ==============================================================================
-- SECTION 7: Statistics for query planner
-- ==============================================================================
-- Increase statistics targets for high-cardinality columns used in filters.
-- This improves query plan quality for large tables.

ALTER TABLE events ALTER COLUMN experiment_id  SET STATISTICS 500;
ALTER TABLE events ALTER COLUMN event_type_id  SET STATISTICS 500;
ALTER TABLE events ALTER COLUMN event_timestamp SET STATISTICS 1000;
ALTER TABLE orders ALTER COLUMN order_timestamp SET STATISTICS 500;
ALTER TABLE sessions ALTER COLUMN session_start SET STATISTICS 500;
ALTER TABLE experiments ALTER COLUMN variant   SET STATISTICS 200;
