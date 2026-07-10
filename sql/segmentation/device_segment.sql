-- ==============================================================================
-- ExperimentIQ — Device Segmentation
-- Purpose: Conversion metrics broken down by device type.
-- ==============================================================================

WITH device_metrics AS (
    SELECT
        experiment_name,
        device_type,
        variant,
        SUM(total_users) AS total_users,
        SUM(purchasers) AS purchasers,
        CASE 
            WHEN SUM(total_users) = 0 THEN 0 
            ELSE SUM(purchasers)::FLOAT / SUM(total_users) 
        END AS conversion_rate
    FROM v_segment_conversion
    GROUP BY experiment_name, device_type, variant
),
ranked_devices AS (
    SELECT
        experiment_name,
        device_type,
        variant,
        total_users,
        purchasers,
        conversion_rate,
        RANK() OVER (PARTITION BY experiment_name, variant ORDER BY conversion_rate DESC) AS cr_rank
    FROM device_metrics
)
SELECT
    experiment_name,
    device_type,
    variant,
    total_users,
    purchasers,
    conversion_rate,
    cr_rank
FROM ranked_devices
ORDER BY experiment_name, device_type, variant;
