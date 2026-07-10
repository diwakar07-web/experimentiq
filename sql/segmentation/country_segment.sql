-- ==============================================================================
-- ExperimentIQ — Country Segmentation
-- Purpose: Conversion metrics by country and region per variant.
-- ==============================================================================

WITH country_metrics AS (
    SELECT
        experiment_name,
        country_name,
        country_code,
        region_name,
        variant,
        SUM(total_users) AS total_users,
        SUM(purchasers) AS purchasers,
        CASE 
            WHEN SUM(total_users) = 0 THEN 0 
            ELSE SUM(purchasers)::FLOAT / SUM(total_users) 
        END AS conversion_rate
    FROM v_segment_conversion
    GROUP BY experiment_name, country_name, country_code, region_name, variant
),
control_country AS (
    SELECT
        experiment_name,
        country_name,
        conversion_rate AS control_cr
    FROM country_metrics
    WHERE variant = 'control'
)
SELECT
    m.experiment_name,
    m.country_name,
    m.country_code,
    m.region_name,
    m.variant,
    m.total_users,
    m.purchasers,
    m.conversion_rate,
    CASE 
        WHEN m.variant = 'control' THEN 0
        WHEN c.control_cr = 0 THEN NULL
        ELSE (m.conversion_rate - c.control_cr) / c.control_cr 
    END AS lift_vs_control
FROM country_metrics m
LEFT JOIN control_country c 
    ON m.experiment_name = c.experiment_name 
   AND m.country_name = c.country_name
ORDER BY m.experiment_name, m.country_name, m.variant;
