-- ==============================================================================
-- ExperimentIQ — Foreign Key & Check Constraints
-- Version: 1.0
-- Execution Order: Run AFTER schema.sql
--
-- All referential integrity constraints are defined here, separated from
-- the table DDL so that tables can be created in any order during schema
-- initialization (e.g., bulk parallel DDL tools).
-- ==============================================================================

-- ==============================================================================
-- SECTION 1: FOREIGN KEY CONSTRAINTS — LOOKUP TABLES
-- ==============================================================================

-- countries → regions
ALTER TABLE countries
    ADD CONSTRAINT fk_countries_region
        FOREIGN KEY (region_id) REFERENCES regions (region_id)
        ON DELETE RESTRICT ON UPDATE CASCADE;

-- ==============================================================================
-- SECTION 2: FOREIGN KEY CONSTRAINTS — users
-- ==============================================================================

ALTER TABLE users
    ADD CONSTRAINT fk_users_country
        FOREIGN KEY (country_id) REFERENCES countries (country_id)
        ON DELETE RESTRICT ON UPDATE CASCADE;

ALTER TABLE users
    ADD CONSTRAINT fk_users_device
        FOREIGN KEY (device_id) REFERENCES devices (device_id)
        ON DELETE RESTRICT ON UPDATE CASCADE;

ALTER TABLE users
    ADD CONSTRAINT fk_users_browser
        FOREIGN KEY (browser_id) REFERENCES browsers (browser_id)
        ON DELETE RESTRICT ON UPDATE CASCADE;

ALTER TABLE users
    ADD CONSTRAINT fk_users_channel
        FOREIGN KEY (channel_id) REFERENCES acquisition_channels (channel_id)
        ON DELETE RESTRICT ON UPDATE CASCADE;

-- ==============================================================================
-- SECTION 3: FOREIGN KEY CONSTRAINTS — experiments
-- ==============================================================================

ALTER TABLE experiments
    ADD CONSTRAINT fk_experiments_user
        FOREIGN KEY (user_id) REFERENCES users (user_id)
        ON DELETE CASCADE ON UPDATE CASCADE;

-- ==============================================================================
-- SECTION 4: FOREIGN KEY CONSTRAINTS — sessions
-- ==============================================================================

ALTER TABLE sessions
    ADD CONSTRAINT fk_sessions_user
        FOREIGN KEY (user_id) REFERENCES users (user_id)
        ON DELETE CASCADE ON UPDATE CASCADE;

ALTER TABLE sessions
    ADD CONSTRAINT fk_sessions_device
        FOREIGN KEY (device_id) REFERENCES devices (device_id)
        ON DELETE RESTRICT ON UPDATE CASCADE;

ALTER TABLE sessions
    ADD CONSTRAINT fk_sessions_browser
        FOREIGN KEY (browser_id) REFERENCES browsers (browser_id)
        ON DELETE RESTRICT ON UPDATE CASCADE;

-- ==============================================================================
-- SECTION 5: FOREIGN KEY CONSTRAINTS — events
-- ==============================================================================

ALTER TABLE events
    ADD CONSTRAINT fk_events_session
        FOREIGN KEY (session_id) REFERENCES sessions (session_id)
        ON DELETE CASCADE ON UPDATE CASCADE;

ALTER TABLE events
    ADD CONSTRAINT fk_events_user
        FOREIGN KEY (user_id) REFERENCES users (user_id)
        ON DELETE CASCADE ON UPDATE CASCADE;

ALTER TABLE events
    ADD CONSTRAINT fk_events_experiment
        FOREIGN KEY (experiment_id) REFERENCES experiments (experiment_id)
        ON DELETE SET NULL ON UPDATE CASCADE;

ALTER TABLE events
    ADD CONSTRAINT fk_events_event_type
        FOREIGN KEY (event_type_id) REFERENCES event_types (event_type_id)
        ON DELETE RESTRICT ON UPDATE CASCADE;

-- ==============================================================================
-- SECTION 6: FOREIGN KEY CONSTRAINTS — orders
-- ==============================================================================

ALTER TABLE orders
    ADD CONSTRAINT fk_orders_user
        FOREIGN KEY (user_id) REFERENCES users (user_id)
        ON DELETE CASCADE ON UPDATE CASCADE;

ALTER TABLE orders
    ADD CONSTRAINT fk_orders_session
        FOREIGN KEY (session_id) REFERENCES sessions (session_id)
        ON DELETE CASCADE ON UPDATE CASCADE;

ALTER TABLE orders
    ADD CONSTRAINT fk_orders_event
        FOREIGN KEY (event_id) REFERENCES events (event_id)
        ON DELETE SET NULL ON UPDATE CASCADE;

-- ==============================================================================
-- SECTION 7: ADDITIONAL CHECK CONSTRAINTS (supplementary)
-- ==============================================================================

-- Ensure signup_date is not in the future (operational constraint)
ALTER TABLE users
    ADD CONSTRAINT chk_users_signup_date_not_future
        CHECK (signup_date <= CURRENT_DATE);

-- Ensure assignment is not before signup
ALTER TABLE experiments
    ADD CONSTRAINT chk_experiments_assignment_reasonable
        CHECK (assignment_timestamp >= '2020-01-01'::TIMESTAMPTZ);

-- Ensure events occur within a plausible date range
ALTER TABLE events
    ADD CONSTRAINT chk_events_timestamp_reasonable
        CHECK (event_timestamp >= '2020-01-01'::TIMESTAMPTZ);

-- Ensure order value is realistic (no single order > $10,000)
ALTER TABLE orders
    ADD CONSTRAINT chk_orders_value_ceiling
        CHECK (order_value <= 10000.00);
