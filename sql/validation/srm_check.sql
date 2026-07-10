-- ==============================================================================
-- ExperimentIQ — Chi-Square SRM Check
-- Purpose: Computes observed vs expected variant counts for Python SRM validation.
-- Python will apply the p-value threshold to determine if SRM exists.
-- ==============================================================================

WITH observed_counts AS (
    SELECT
        experiment_name,
        COUNT(CASE WHEN variant = 'control' THEN 1 END) AS control_users,
        COUNT(CASE WHEN variant = 'variant' THEN 1 END) AS variant_users,
        COUNT(*) AS total_users
    FROM experiments
    WHERE is_holdout = FALSE
    GROUP BY experiment_name
)
SELECT
    experiment_name,
    control_users,
    variant_users,
    (total_users * 0.5) AS expected_control,
    (total_users * 0.5) AS expected_variant,
    -- Chi-square statistic formula: sum((O - E)^2 / E)
    (POWER(control_users - (total_users * 0.5), 2) / (total_users * 0.5)) +
    (POWER(variant_users - (total_users * 0.5), 2) / (total_users * 0.5)) AS chi_square_stat,
    -- Python will calculate the p-value using scipy.stats and set the flag.
    NULL::BOOLEAN AS srm_detected_flag
FROM observed_counts
ORDER BY experiment_name;
