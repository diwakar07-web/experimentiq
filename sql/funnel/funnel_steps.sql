-- ==============================================================================
-- ExperimentIQ — Funnel Steps
-- Purpose: Unpivots the funnel steps view into rows for step-by-step analysis.
-- ==============================================================================

WITH unpivoted_funnel AS (
    SELECT experiment_name, variant, 1 AS step_order, '1. Landing' AS step_name, landing_users AS users_reached, total_users FROM v_funnel_steps
    UNION ALL
    SELECT experiment_name, variant, 2 AS step_order, '2. Product' AS step_name, product_users AS users_reached, total_users FROM v_funnel_steps
    UNION ALL
    SELECT experiment_name, variant, 3 AS step_order, '3. Cart' AS step_name, cart_users AS users_reached, total_users FROM v_funnel_steps
    UNION ALL
    SELECT experiment_name, variant, 4 AS step_order, '4. Checkout' AS step_name, checkout_users AS users_reached, total_users FROM v_funnel_steps
    UNION ALL
    SELECT experiment_name, variant, 5 AS step_order, '5. Purchase' AS step_name, purchase_users AS users_reached, total_users FROM v_funnel_steps
),
funnel_with_lag AS (
    SELECT
        experiment_name,
        variant,
        step_name,
        step_order,
        users_reached,
        total_users,
        LAG(users_reached, 1) OVER (PARTITION BY experiment_name, variant ORDER BY step_order) AS prev_users_reached
    FROM unpivoted_funnel
)
SELECT
    experiment_name,
    variant,
    step_name,
    step_order,
    users_reached,
    COALESCE(prev_users_reached, total_users) AS users_at_step,
    CASE 
        WHEN COALESCE(prev_users_reached, total_users) = 0 THEN 0 
        ELSE users_reached::FLOAT / COALESCE(prev_users_reached, total_users) 
    END AS step_conversion_rate,
    CASE 
        WHEN total_users = 0 THEN 0 
        ELSE users_reached::FLOAT / total_users 
    END AS cumulative_conversion_rate,
    COALESCE(prev_users_reached, total_users) - users_reached AS drop_off_count,
    CASE 
        WHEN COALESCE(prev_users_reached, total_users) = 0 THEN 0 
        ELSE (COALESCE(prev_users_reached, total_users) - users_reached)::FLOAT / COALESCE(prev_users_reached, total_users) 
    END AS drop_off_rate
FROM funnel_with_lag
ORDER BY experiment_name, variant, step_order;
