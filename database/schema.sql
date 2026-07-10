-- ==============================================================================
-- ExperimentIQ — PostgreSQL Database Schema
-- Version: 1.0
-- Description: Complete normalized schema for the A/B testing platform.
--
-- Execution Order:
--   1. This file (schema.sql)   — tables & sequences
--   2. constraints.sql          — foreign keys & check constraints
--   3. indexes.sql              — performance indexes
--   4. views.sql                — analytical views & materialized views
--
-- Design Principles:
--   - Fully normalized (3NF). No denormalized raw tables.
--   - All IDs use UUIDs (v4) for distributed safety.
--   - All timestamps are stored as TIMESTAMPTZ (UTC).
--   - Lookup tables are pre-seeded; they drive FOREIGN KEY constraints.
-- ==============================================================================

-- Wipe existing schema to ensure idempotency on pipeline re-runs
DROP SCHEMA public CASCADE;
CREATE SCHEMA public;

-- Enable uuid-ossp extension for UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Enable pg_stat_statements for query performance monitoring
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- ==============================================================================
-- SCHEMA NAMESPACE
-- ==============================================================================
-- All objects live in the public schema for simplicity.
-- In a production multi-tenant system, a named schema would be used.

-- ==============================================================================
-- SECTION 1: LOOKUP TABLES
-- These tables define valid reference values and are seeded at init time.
-- They have no dependency on other tables.
-- ==============================================================================

-- ------------------------------------------------------------------------------
-- 1.1 regions
-- Geographic regions grouping multiple countries.
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS regions (
    region_id   SMALLINT        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    region_name VARCHAR(100)    NOT NULL,

    CONSTRAINT uq_regions_name UNIQUE (region_name)
);

COMMENT ON TABLE  regions             IS 'Geographic regions grouping countries.';
COMMENT ON COLUMN regions.region_id   IS 'Surrogate primary key (auto-generated).';
COMMENT ON COLUMN regions.region_name IS 'Human-readable region name (e.g., North America).';

-- ------------------------------------------------------------------------------
-- 1.2 countries
-- Individual countries with ISO 3166-1 alpha-2 codes.
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS countries (
    country_id   SMALLINT        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    country_code CHAR(2)         NOT NULL,
    country_name VARCHAR(100)    NOT NULL,
    region_id    SMALLINT        NOT NULL,

    CONSTRAINT uq_countries_code UNIQUE (country_code),
    CONSTRAINT uq_countries_name UNIQUE (country_name)
);

COMMENT ON TABLE  countries              IS 'Countries with ISO codes and region grouping.';
COMMENT ON COLUMN countries.country_id   IS 'Surrogate primary key.';
COMMENT ON COLUMN countries.country_code IS 'ISO 3166-1 alpha-2 country code.';
COMMENT ON COLUMN countries.country_name IS 'Full country name.';
COMMENT ON COLUMN countries.region_id    IS 'FK → regions.';

-- ------------------------------------------------------------------------------
-- 1.3 devices
-- Device type categories (not specific hardware models).
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS devices (
    device_id   SMALLINT        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    device_type VARCHAR(50)     NOT NULL,

    CONSTRAINT uq_devices_type UNIQUE (device_type)
);

COMMENT ON TABLE  devices             IS 'Device type lookup (mobile, desktop, tablet).';
COMMENT ON COLUMN devices.device_id   IS 'Surrogate primary key.';
COMMENT ON COLUMN devices.device_type IS 'Device category name.';

-- ------------------------------------------------------------------------------
-- 1.4 browsers
-- Web browser names.
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS browsers (
    browser_id   SMALLINT        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    browser_name VARCHAR(100)    NOT NULL,

    CONSTRAINT uq_browsers_name UNIQUE (browser_name)
);

COMMENT ON TABLE  browsers              IS 'Web browser lookup table.';
COMMENT ON COLUMN browsers.browser_id   IS 'Surrogate primary key.';
COMMENT ON COLUMN browsers.browser_name IS 'Browser name (e.g., Chrome, Firefox).';

-- ------------------------------------------------------------------------------
-- 1.5 acquisition_channels
-- Marketing / traffic source channels.
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS acquisition_channels (
    channel_id   SMALLINT        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    channel_name VARCHAR(100)    NOT NULL,

    CONSTRAINT uq_acquisition_channels_name UNIQUE (channel_name)
);

COMMENT ON TABLE  acquisition_channels              IS 'User acquisition / traffic source channels.';
COMMENT ON COLUMN acquisition_channels.channel_id   IS 'Surrogate primary key.';
COMMENT ON COLUMN acquisition_channels.channel_name IS 'Channel name (e.g., organic_search, paid_social).';

-- ------------------------------------------------------------------------------
-- 1.6 event_types
-- Catalogue of all trackable event names and their funnel category.
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS event_types (
    event_type_id   SMALLINT        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_name      VARCHAR(100)    NOT NULL,
    event_category  VARCHAR(50)     NOT NULL,
    funnel_step     SMALLINT        NULL,

    CONSTRAINT uq_event_types_name     UNIQUE (event_name),
    CONSTRAINT chk_event_category      CHECK (event_category IN (
        'navigation', 'engagement', 'commerce', 'error', 'system'
    )),
    CONSTRAINT chk_funnel_step         CHECK (funnel_step IS NULL OR funnel_step BETWEEN 1 AND 10)
);

COMMENT ON TABLE  event_types                IS 'Catalogue of trackable events with funnel classification.';
COMMENT ON COLUMN event_types.event_type_id  IS 'Surrogate primary key.';
COMMENT ON COLUMN event_types.event_name     IS 'Unique event identifier string.';
COMMENT ON COLUMN event_types.event_category IS 'High-level event category.';
COMMENT ON COLUMN event_types.funnel_step    IS 'Ordered position in the conversion funnel (1=top).';

-- ==============================================================================
-- SECTION 2: CORE TABLES
-- Primary business entities. Each references only lookup tables or other
-- core tables that appear earlier in this file.
-- ==============================================================================

-- ------------------------------------------------------------------------------
-- 2.1 users
-- One row per unique user. Created once; not updated after insert.
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    user_id            UUID            DEFAULT uuid_generate_v4() PRIMARY KEY,
    signup_date        DATE            NOT NULL,
    country_id         SMALLINT        NOT NULL,
    device_id          SMALLINT        NOT NULL,
    browser_id         SMALLINT        NOT NULL,
    channel_id         SMALLINT        NOT NULL,
    customer_type      VARCHAR(20)     NOT NULL,
    operating_system   VARCHAR(50)     NULL,
    is_returning       BOOLEAN         NOT NULL DEFAULT FALSE,
    created_at         TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_users_customer_type CHECK (customer_type IN ('new', 'returning', 'high_value'))
);

COMMENT ON TABLE  users                  IS 'One row per unique user. Core user profile table.';
COMMENT ON COLUMN users.user_id          IS 'UUID primary key.';
COMMENT ON COLUMN users.signup_date      IS 'Date the user first registered.';
COMMENT ON COLUMN users.country_id       IS 'FK → countries.';
COMMENT ON COLUMN users.device_id        IS 'Primary device type of the user.';
COMMENT ON COLUMN users.browser_id       IS 'Primary browser of the user.';
COMMENT ON COLUMN users.channel_id       IS 'Acquisition channel (how user arrived).';
COMMENT ON COLUMN users.customer_type    IS 'Customer segment: new, returning, or high_value.';
COMMENT ON COLUMN users.operating_system IS 'Operating system (e.g., Windows, macOS, iOS, Android).';
COMMENT ON COLUMN users.is_returning     IS 'True if user had a prior history before signup_date.';

-- ------------------------------------------------------------------------------
-- 2.2 experiments
-- One row per user-experiment assignment.
-- A user is assigned exactly once to exactly one variant.
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS experiments (
    experiment_id        UUID            DEFAULT uuid_generate_v4() PRIMARY KEY,
    experiment_name      VARCHAR(200)    NOT NULL,
    variant              VARCHAR(20)     NOT NULL,
    user_id              UUID            NOT NULL,
    assignment_timestamp TIMESTAMPTZ     NOT NULL,
    is_holdout           BOOLEAN         NOT NULL DEFAULT FALSE,

    CONSTRAINT chk_experiments_variant  CHECK (variant IN ('control', 'variant')),
    CONSTRAINT uq_experiments_user      UNIQUE (user_id, experiment_name)
);

COMMENT ON TABLE  experiments                        IS 'Experiment variant assignments. One row per user per experiment.';
COMMENT ON COLUMN experiments.experiment_id          IS 'UUID primary key.';
COMMENT ON COLUMN experiments.experiment_name        IS 'Logical experiment identifier string.';
COMMENT ON COLUMN experiments.variant                IS 'Group assignment: control or variant.';
COMMENT ON COLUMN experiments.user_id                IS 'FK → users.';
COMMENT ON COLUMN experiments.assignment_timestamp   IS 'When the user was assigned to this variant.';
COMMENT ON COLUMN experiments.is_holdout             IS 'If true, user is in a holdout group (excluded from analysis).';

-- ------------------------------------------------------------------------------
-- 2.3 sessions
-- One row per user browsing session. A user may have multiple sessions.
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sessions (
    session_id         UUID            DEFAULT uuid_generate_v4() PRIMARY KEY,
    user_id            UUID            NOT NULL,
    session_start      TIMESTAMPTZ     NOT NULL,
    session_end        TIMESTAMPTZ     NOT NULL,
    duration_seconds   INTEGER         NOT NULL,
    device_id          SMALLINT        NOT NULL,
    browser_id         SMALLINT        NOT NULL,
    page_count         SMALLINT        NOT NULL DEFAULT 1,
    is_bounce          BOOLEAN         NOT NULL DEFAULT FALSE,

    CONSTRAINT chk_sessions_end_after_start  CHECK (session_end >= session_start),
    CONSTRAINT chk_sessions_duration         CHECK (duration_seconds >= 0),
    CONSTRAINT chk_sessions_page_count       CHECK (page_count >= 1)
);

COMMENT ON TABLE  sessions                   IS 'One row per user browsing session.';
COMMENT ON COLUMN sessions.session_id        IS 'UUID primary key.';
COMMENT ON COLUMN sessions.user_id           IS 'FK → users.';
COMMENT ON COLUMN sessions.session_start     IS 'UTC timestamp when the session began.';
COMMENT ON COLUMN sessions.session_end       IS 'UTC timestamp when the session ended.';
COMMENT ON COLUMN sessions.duration_seconds  IS 'Computed session duration in seconds.';
COMMENT ON COLUMN sessions.device_id         IS 'Device used during this session.';
COMMENT ON COLUMN sessions.browser_id        IS 'Browser used during this session.';
COMMENT ON COLUMN sessions.page_count        IS 'Number of pages viewed during the session.';
COMMENT ON COLUMN sessions.is_bounce         IS 'True if user left after only one page.';

-- ------------------------------------------------------------------------------
-- 2.4 events
-- One row per individual tracked event within a session.
-- This is the highest-volume table in the system.
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS events (
    event_id         UUID            DEFAULT uuid_generate_v4() PRIMARY KEY,
    session_id       UUID            NOT NULL,
    user_id          UUID            NOT NULL,
    experiment_id    UUID            NULL,
    event_type_id    SMALLINT        NOT NULL,
    event_timestamp  TIMESTAMPTZ     NOT NULL,
    page_url         VARCHAR(500)    NULL,
    revenue          NUMERIC(12, 4)  NULL,
    is_mobile        BOOLEAN         NOT NULL DEFAULT FALSE,

    CONSTRAINT chk_events_revenue CHECK (revenue IS NULL OR revenue >= 0)
);

COMMENT ON TABLE  events                   IS 'Individual tracked user events. Highest-volume table.';
COMMENT ON COLUMN events.event_id          IS 'UUID primary key.';
COMMENT ON COLUMN events.session_id        IS 'FK → sessions.';
COMMENT ON COLUMN events.user_id           IS 'FK → users (denormalized for query performance).';
COMMENT ON COLUMN events.experiment_id     IS 'FK → experiments (nullable: events before assignment).';
COMMENT ON COLUMN events.event_type_id     IS 'FK → event_types.';
COMMENT ON COLUMN events.event_timestamp   IS 'UTC timestamp of the event.';
COMMENT ON COLUMN events.page_url          IS 'URL of the page where the event occurred.';
COMMENT ON COLUMN events.revenue           IS 'Revenue associated with this event (NULL if non-purchase).';
COMMENT ON COLUMN events.is_mobile         IS 'True if the event occurred on a mobile device.';

-- ------------------------------------------------------------------------------
-- 2.5 orders
-- One row per completed purchase. May include refunded orders.
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS orders (
    order_id         UUID            DEFAULT uuid_generate_v4() PRIMARY KEY,
    user_id          UUID            NOT NULL,
    session_id       UUID            NOT NULL,
    event_id         UUID            NULL,
    order_timestamp  TIMESTAMPTZ     NOT NULL,
    order_value      NUMERIC(12, 2)  NOT NULL,
    payment_method   VARCHAR(50)     NOT NULL,
    is_refund        BOOLEAN         NOT NULL DEFAULT FALSE,
    payment_status   VARCHAR(30)     NOT NULL DEFAULT 'completed',

    CONSTRAINT chk_orders_order_value     CHECK (order_value > 0),
    CONSTRAINT chk_orders_payment_status  CHECK (payment_status IN (
        'completed', 'failed', 'pending', 'refunded'
    )),
    CONSTRAINT chk_orders_payment_method  CHECK (payment_method IN (
        'credit_card', 'debit_card', 'paypal', 'apple_pay', 'google_pay', 'bank_transfer'
    ))
);

COMMENT ON TABLE  orders                  IS 'Completed purchase transactions.';
COMMENT ON COLUMN orders.order_id         IS 'UUID primary key.';
COMMENT ON COLUMN orders.user_id          IS 'FK → users.';
COMMENT ON COLUMN orders.session_id       IS 'FK → sessions (the session in which purchase occurred).';
COMMENT ON COLUMN orders.event_id         IS 'FK → events (the purchase event, if tracked).';
COMMENT ON COLUMN orders.order_timestamp  IS 'UTC timestamp of the purchase.';
COMMENT ON COLUMN orders.order_value      IS 'Total order value in USD.';
COMMENT ON COLUMN orders.payment_method   IS 'Payment method used.';
COMMENT ON COLUMN orders.is_refund        IS 'True if this order was subsequently refunded.';
COMMENT ON COLUMN orders.payment_status   IS 'Final payment status.';

-- ==============================================================================
-- SECTION 3: LOOKUP TABLE SEED DATA
-- Reference data seeded inline. This data never changes at runtime.
-- ==============================================================================

-- Regions
INSERT INTO regions (region_name) VALUES
    ('North America'),
    ('Europe'),
    ('Asia Pacific'),
    ('Latin America'),
    ('Middle East & Africa')
ON CONFLICT (region_name) DO NOTHING;

-- Countries (sample of 20 representative countries)
INSERT INTO countries (country_code, country_name, region_id) VALUES
    ('US', 'United States',    (SELECT region_id FROM regions WHERE region_name = 'North America')),
    ('CA', 'Canada',           (SELECT region_id FROM regions WHERE region_name = 'North America')),
    ('MX', 'Mexico',           (SELECT region_id FROM regions WHERE region_name = 'Latin America')),
    ('BR', 'Brazil',           (SELECT region_id FROM regions WHERE region_name = 'Latin America')),
    ('AR', 'Argentina',        (SELECT region_id FROM regions WHERE region_name = 'Latin America')),
    ('GB', 'United Kingdom',   (SELECT region_id FROM regions WHERE region_name = 'Europe')),
    ('DE', 'Germany',          (SELECT region_id FROM regions WHERE region_name = 'Europe')),
    ('FR', 'France',           (SELECT region_id FROM regions WHERE region_name = 'Europe')),
    ('IT', 'Italy',            (SELECT region_id FROM regions WHERE region_name = 'Europe')),
    ('ES', 'Spain',            (SELECT region_id FROM regions WHERE region_name = 'Europe')),
    ('NL', 'Netherlands',      (SELECT region_id FROM regions WHERE region_name = 'Europe')),
    ('SE', 'Sweden',           (SELECT region_id FROM regions WHERE region_name = 'Europe')),
    ('AU', 'Australia',        (SELECT region_id FROM regions WHERE region_name = 'Asia Pacific')),
    ('JP', 'Japan',            (SELECT region_id FROM regions WHERE region_name = 'Asia Pacific')),
    ('IN', 'India',            (SELECT region_id FROM regions WHERE region_name = 'Asia Pacific')),
    ('SG', 'Singapore',        (SELECT region_id FROM regions WHERE region_name = 'Asia Pacific')),
    ('KR', 'South Korea',      (SELECT region_id FROM regions WHERE region_name = 'Asia Pacific')),
    ('CN', 'China',            (SELECT region_id FROM regions WHERE region_name = 'Asia Pacific')),
    ('AE', 'United Arab Emirates', (SELECT region_id FROM regions WHERE region_name = 'Middle East & Africa')),
    ('ZA', 'South Africa',     (SELECT region_id FROM regions WHERE region_name = 'Middle East & Africa'))
ON CONFLICT (country_code) DO NOTHING;

-- Devices
INSERT INTO devices (device_type) VALUES
    ('desktop'), ('mobile'), ('tablet')
ON CONFLICT (device_type) DO NOTHING;

-- Browsers
INSERT INTO browsers (browser_name) VALUES
    ('Chrome'), ('Firefox'), ('Safari'), ('Edge'), ('Opera'), ('Samsung Internet')
ON CONFLICT (browser_name) DO NOTHING;

-- Acquisition Channels
INSERT INTO acquisition_channels (channel_name) VALUES
    ('organic_search'),
    ('paid_search'),
    ('paid_social'),
    ('organic_social'),
    ('email'),
    ('direct'),
    ('referral'),
    ('display_ads'),
    ('affiliate')
ON CONFLICT (channel_name) DO NOTHING;

-- Event Types (funnel-ordered)
INSERT INTO event_types (event_name, event_category, funnel_step) VALUES
    ('page_view',           'navigation',  1),
    ('product_view',        'navigation',  2),
    ('search',              'engagement',  NULL),
    ('add_to_cart',         'commerce',    3),
    ('cart_view',           'navigation',  3),
    ('checkout_start',      'commerce',    4),
    ('checkout_address',    'commerce',    4),
    ('checkout_payment',    'commerce',    4),
    ('purchase',            'commerce',    5),
    ('purchase_failed',     'error',       5),
    ('refund',              'commerce',    NULL),
    ('session_start',       'system',      NULL),
    ('session_end',         'system',      NULL),
    ('scroll',              'engagement',  NULL),
    ('click',               'engagement',  NULL),
    ('wishlist_add',        'engagement',  NULL),
    ('coupon_applied',      'commerce',    NULL),
    ('checkout_abandoned',  'commerce',    NULL)
ON CONFLICT (event_name) DO NOTHING;
