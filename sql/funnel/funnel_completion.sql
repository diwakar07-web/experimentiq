-- ==============================================================================
-- ExperimentIQ — Funnel Completion Comparison
-- Purpose: Side-by-side funnel conversion lift comparison between control and variant.
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
funnel_rates AS (
    SELECT
        experiment_name,
        variant,
        step_name,
        step_order,
        users_reached,
        total_users,
        CASE 
            WHEN total_users = 0 THEN 0 
            ELSE users_reached::FLOAT / total_users 
        END AS cumulative_rate
    FROM unpivoted_funnel
),
control_funnel AS (
    SELECT experiment_name, step_order, cumulative_rate AS control_rate
    FROM funnel_rates
    WHERE variant = 'control'
),
variant_funnel AS (
    SELECT experiment_name, step_order, step_name, users_reached, total_users, cumulative_rate AS variant_rate
    FROM funnel_rates
    WHERE variant = 'variant'
)
SELECT
    v.experiment_name,
    v.step_order,
    v.step_name,
    v.users_reached AS variant_users_reached,
    v.total_users AS variant_total_users,
    c.control_rate,
    v.variant_rate,
    v.variant_rate - c.control_rate AS absolute_lift,
    CASE 
        WHEN c.control_rate = 0 THEN NULL 
        ELSE (v.variant_rate - c.control_rate) / c.control_rate 
    END AS relative_lift
FROM variant_funnel v
JOIN control_funnel c ON v.experiment_name = c.experiment_name AND v.step_order = c.step_order
ORDER BY v.experiment_name, v.step_order;
