-- Range Validity (DuckDB)
-- Detects IQR outliers (1.5×IQR rule) for numeric non-categorical variables
-- with >1,000 rows per Variable_name. IQR is computed per Variable_name
-- (pooled across tables), matching the original Python implementation.
--
-- Parameter: {quiq_csv} — path to QUIQ-format CSV file

WITH numeric_vals AS (
    SELECT
        Original_table_name,
        Variable_name,
        Patient_id,
        Event_date,
        TRY_CAST(Value AS DOUBLE) AS Value
    FROM read_csv_auto('{quiq_csv}', all_varchar=true)
    WHERE Variable_type ILIKE '%numeric%'
      AND TRY_CAST(Is_categorical AS INTEGER) = 0
      AND Value IS NOT NULL
      AND TRY_CAST(Value AS DOUBLE) IS NOT NULL
),

-- Filter: only Variable_name groups with >1000 rows (across all tables)
var_counts AS (
    SELECT Variable_name, COUNT(*) AS cnt
    FROM numeric_vals
    GROUP BY Variable_name
),

filtered AS (
    SELECT n.*
    FROM numeric_vals n
    JOIN var_counts v ON n.Variable_name = v.Variable_name
    WHERE v.cnt > 1000
),

-- IQR stats computed per Variable_name (pooled across tables)
iqr_stats AS (
    SELECT
        Variable_name,
        PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY Value) AS q25,
        PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY Value) AS q75
    FROM filtered
    GROUP BY Variable_name
),

with_bounds AS (
    SELECT
        f.*,
        s.q25,
        s.q75,
        s.q25 - 1.5 * (s.q75 - s.q25) AS lowest,
        s.q75 + 1.5 * (s.q75 - s.q25) AS highest
    FROM filtered f
    JOIN iqr_stats s ON f.Variable_name = s.Variable_name
),

outlier_flags AS (
    SELECT *,
        CASE
            WHEN Value < lowest THEN 'under'
            WHEN Value > highest THEN 'upper'
            ELSE NULL
        END AS Outlier_direction
    FROM with_bounds
),

summary AS (
    SELECT
        Original_table_name,
        Variable_name,
        COUNT(*)                                                                    AS Total_num,
        COUNT(*) FILTER (WHERE Outlier_direction = 'under')                        AS Outlier_under_num,
        COUNT(*) FILTER (WHERE Outlier_direction = 'upper')                        AS Outlier_upper_num,
        COUNT(*) FILTER (WHERE Outlier_direction IS NOT NULL)                      AS Outlier_total_num,
        ROUND(COUNT(*) FILTER (WHERE Outlier_direction = 'under')::DOUBLE
              / COUNT(*), 3)                                                        AS Outlier_under_proportion,
        ROUND(COUNT(*) FILTER (WHERE Outlier_direction = 'upper')::DOUBLE
              / COUNT(*), 3)                                                        AS Outlier_upper_proportion,
        ROUND(COUNT(*) FILTER (WHERE Outlier_direction IS NOT NULL)::DOUBLE
              / COUNT(*), 3)                                                        AS Outlier_total_proportion,
        ROUND((COUNT(*) - COUNT(*) FILTER (WHERE Outlier_direction IS NOT NULL))::DOUBLE
              / COUNT(*) * 100, 2)                                                  AS "Range Validity (%)"
    FROM outlier_flags
    GROUP BY Original_table_name, Variable_name
    ORDER BY Total_num DESC
)

SELECT * FROM summary
