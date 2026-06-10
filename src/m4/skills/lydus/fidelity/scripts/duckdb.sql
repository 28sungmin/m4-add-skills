-- ═══════════════════════════════════════════════════════════════════
-- LYDUS Fidelity (DuckDB version, v1.0 260610)
--
-- 참조: LYDUS_Fidelity.py (이성민 작성)
--       LYDUS 품질관리 프로그램 활용 가이드라인
--
-- 변환 전략
--   4개 카테고리 (Event / Diagnosis / Prescription / Procedure) 를 각각 처리 후 UNION ALL
--
--   ① Event      : Mapping_info_1 = 'event'
--                  (table, variable, patient) 별 빈도 → (table, variable) 별 집계
--                  Value = NULL (값별 구분 없음)
--
--   ② Diagnosis  : Mapping_info_1 = 'diagnosis', Is_categorical = 1
--   ③ Prescription: Mapping_info_1 = 'prescription', Is_categorical = 1
--   ④ Procedure  : Mapping_info_1 = 'procedure', Is_categorical = 1
--                  (table, variable, value, patient) 별 빈도 → (table, variable, value) 별 집계
--
--   집계 지표: Patient_num (환자 수), Mean (환자별 평균 빈도), Std (표준편차)
--   Weighted Fidelity = Σ(Patient_num × Mean) / Σ(Patient_num)
--
-- < 실행 방법 >
-- Python:
--   import duckdb
--   sql = open('scripts/duckdb.sql').read().replace('{quiq_csv}', '/path/to/quiq.csv')
--   df = duckdb.sql(sql).df()
-- ═══════════════════════════════════════════════════════════════════

WITH

-- ── ① Event ───────────────────────────────────────────────────────
-- Python: df_event groupby(table, variable, patient) → count → groupby(table, variable)
event_per_patient AS (
    SELECT
        Original_table_name,
        Variable_name,
        Patient_id,
        COUNT(*) AS Frequency
    FROM read_csv_auto('{quiq_csv}')
    WHERE lower(coalesce(Mapping_info_1, '')) LIKE '%event%'
      AND Patient_id IS NOT NULL
      AND Value IS NOT NULL
    GROUP BY Original_table_name, Variable_name, Patient_id
),
event_agg AS (
    SELECT
        Original_table_name,
        Variable_name,
        NULL::VARCHAR                    AS Value,
        COUNT(DISTINCT Patient_id)       AS Patient_num,
        ROUND(AVG(Frequency), 2)         AS Mean,
        ROUND(STDDEV(Frequency), 2)      AS Std
    FROM event_per_patient
    GROUP BY Original_table_name, Variable_name
),

-- ── ② Diagnosis ───────────────────────────────────────────────────
-- Python: df_diagnosis (Is_categorical=1) groupby(table, variable, value, patient) → groupby(table, variable, value)
diagnosis_per_patient AS (
    SELECT
        Original_table_name,
        Variable_name,
        Value,
        Patient_id,
        COUNT(*) AS Frequency
    FROM read_csv_auto('{quiq_csv}')
    WHERE lower(coalesce(Mapping_info_1, '')) LIKE '%diagnosis%'
      AND TRY_CAST(Is_categorical AS INTEGER) = 1
      AND Patient_id IS NOT NULL
      AND Value IS NOT NULL
    GROUP BY Original_table_name, Variable_name, Value, Patient_id
),
diagnosis_agg AS (
    SELECT
        Original_table_name,
        Variable_name,
        Value,
        COUNT(DISTINCT Patient_id)       AS Patient_num,
        ROUND(AVG(Frequency), 2)         AS Mean,
        ROUND(STDDEV(Frequency), 2)      AS Std
    FROM diagnosis_per_patient
    GROUP BY Original_table_name, Variable_name, Value
),

-- ── ③ Prescription ────────────────────────────────────────────────
prescription_per_patient AS (
    SELECT
        Original_table_name,
        Variable_name,
        Value,
        Patient_id,
        COUNT(*) AS Frequency
    FROM read_csv_auto('{quiq_csv}')
    WHERE lower(coalesce(Mapping_info_1, '')) LIKE '%prescription%'
      AND TRY_CAST(Is_categorical AS INTEGER) = 1
      AND Patient_id IS NOT NULL
      AND Value IS NOT NULL
    GROUP BY Original_table_name, Variable_name, Value, Patient_id
),
prescription_agg AS (
    SELECT
        Original_table_name,
        Variable_name,
        Value,
        COUNT(DISTINCT Patient_id)       AS Patient_num,
        ROUND(AVG(Frequency), 2)         AS Mean,
        ROUND(STDDEV(Frequency), 2)      AS Std
    FROM prescription_per_patient
    GROUP BY Original_table_name, Variable_name, Value
),

-- ── ④ Procedure ───────────────────────────────────────────────────
procedure_per_patient AS (
    SELECT
        Original_table_name,
        Variable_name,
        Value,
        Patient_id,
        COUNT(*) AS Frequency
    FROM read_csv_auto('{quiq_csv}')
    WHERE lower(coalesce(Mapping_info_1, '')) LIKE '%procedure%'
      AND TRY_CAST(Is_categorical AS INTEGER) = 1
      AND Patient_id IS NOT NULL
      AND Value IS NOT NULL
    GROUP BY Original_table_name, Variable_name, Value, Patient_id
),
procedure_agg AS (
    SELECT
        Original_table_name,
        Variable_name,
        Value,
        COUNT(DISTINCT Patient_id)       AS Patient_num,
        ROUND(AVG(Frequency), 2)         AS Mean,
        ROUND(STDDEV(Frequency), 2)      AS Std
    FROM procedure_per_patient
    GROUP BY Original_table_name, Variable_name, Value
)

-- ── 최종 출력: 4개 카테고리 UNION ALL ──────────────────────────────
SELECT * FROM event_agg
UNION ALL SELECT * FROM diagnosis_agg
UNION ALL SELECT * FROM prescription_agg
UNION ALL SELECT * FROM procedure_agg
ORDER BY Original_table_name, Variable_name, Value
