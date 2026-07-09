-- ═══════════════════════════════════════════════════════════════════
-- MIMIC-IV → VIA Table (BigQuery version, 2026-06-21)
--
-- VIA (Variable Information Archive): QUIQ 테이블에 등장하는 모든
-- (Original_table_name, Variable_name) 조합에 대해 변수 설명(Description)을
-- BigQuery INFORMATION_SCHEMA.COLUMNS 에서 추출한다.
--
-- < 컬럼 매핑 >
--   UPPER(table_name)  → Original_table_name  (QUIQ 포맷과 동일)
--   column_name        → Variable_name
--   COALESCE(description, generated_text) → Description
--
-- < 실행 방법 >
--   from google.cloud import bigquery
--   client = bigquery.Client(project="cmi-lab-492906")
--   sql = open("bigquery.sql").read().replace("{bq_project}", "cmi-lab")
--   df = client.query(sql).to_dataframe()
-- ═══════════════════════════════════════════════════════════════════

SELECT
    UPPER(table_name) AS Original_table_name,
    column_name       AS Variable_name,
    CONCAT(column_name, ' (', data_type, ') — column of table ', UPPER(table_name)) AS Description
FROM `{bq_project}`.mimiciv_3_1_hosp.INFORMATION_SCHEMA.COLUMNS
WHERE is_system_defined = 'NO'

UNION ALL

SELECT
    UPPER(table_name),
    column_name,
    CONCAT(column_name, ' (', data_type, ') — column of table ', UPPER(table_name))
FROM `{bq_project}`.mimiciv_3_1_icu.INFORMATION_SCHEMA.COLUMNS
WHERE is_system_defined = 'NO'

UNION ALL

SELECT
    UPPER(table_name),
    column_name,
    CONCAT(column_name, ' (', data_type, ') — column of table ', UPPER(table_name))
FROM `{bq_project}`.MIMIC_IV_ED.INFORMATION_SCHEMA.COLUMNS
WHERE is_system_defined = 'NO'

UNION ALL

SELECT
    UPPER(table_name),
    column_name,
    CONCAT(column_name, ' (', data_type, ') — column of table ', UPPER(table_name))
FROM `{bq_project}`.MIMIC_IV_NOTE.INFORMATION_SCHEMA.COLUMNS
WHERE is_system_defined = 'NO'

ORDER BY Original_table_name, Variable_name
