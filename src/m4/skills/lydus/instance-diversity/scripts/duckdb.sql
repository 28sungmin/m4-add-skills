-- ═══════════════════════════════════════════════════════════════════
-- LYDUS Instance Diversity (DuckDB version, v1.0 260610)
--
-- 참조: LYDUS_Instance_Diversity.py (이성민 작성)
--       LYDUS 품질관리 프로그램 활용 가이드라인
--
-- 개념
--   ClassKey = (Original_table_name, Variable_name, Value)
--   각 ClassKey 에 대해 환자(Patient_id)별 발생 횟수(Instance_Count) 분포를 구하고,
--   그 분포의 다양성을 측정.
--
--   Instance Diversity (%) = 환자 수 / 총 발생 수 × 100
--     → 값이 클수록 환자 1인당 평균 발생 횟수가 적음 (다양한 환자에 분산)
--
--   Gini-Simpson Index (%) = (1 - Σp²) × 100
--     p = 특정 발생 횟수를 가진 환자 수 / 총 발생 수
--     → class diversity 와 동일한 Simpson 공식, 발생 횟수 분포에 적용
--
-- 변환 전략
--   ① filtered         : event | diagnosis | (prescription+drug) | procedure,
--                         Is_categorical=1, Patient_id/Variable_name/Value non-null
--   ② class_patient    : (ClassKey, Patient_id) 별 발생 횟수 (Instance_Count)
--   ③ class_totals     : ClassKey 별 환자 수 / 총 발생 수
--   ④ instance_counter : (ClassKey, Instance_Count) 별 환자 수 → 확률 계산
--   ⑤ diversity_summary: Instance Diversity (%) / Gini-Simpson Index (%) 최종 집계
--
-- < 실행 방법 >
-- Python:
--   import duckdb
--   sql = open('scripts/duckdb.sql').read().replace('{quiq_csv}', '/path/to/quiq.csv')
--   df = duckdb.sql(sql).df()
-- ═══════════════════════════════════════════════════════════════════

WITH

-- ── ① 필터링 ──────────────────────────────────────────────────────
-- Python: df0~df3 concat + Is_categorical=1 + dropna
filtered AS (
    SELECT
        Original_table_name,
        Variable_name,
        Value,
        Patient_id
    FROM read_csv_auto('{quiq_csv}')
    WHERE (
        lower(coalesce(Mapping_info_1, '')) LIKE '%event%'
        OR lower(coalesce(Mapping_info_1, '')) LIKE '%diagnosis%'
        OR (lower(coalesce(Mapping_info_1, '')) LIKE '%prescription%'
            AND lower(coalesce(Mapping_info_2, '')) LIKE '%drug%')
        OR lower(coalesce(Mapping_info_1, '')) LIKE '%procedure%'
    )
    AND TRY_CAST(Is_categorical AS INTEGER) = 1
    AND Patient_id IS NOT NULL
    AND Variable_name IS NOT NULL
    AND Value IS NOT NULL
),

-- ── ② (ClassKey, Patient_id) 별 발생 횟수 ─────────────────────────
-- Python: df.groupby(["Class", "Instance"]).size()
class_patient AS (
    SELECT
        Original_table_name,
        Variable_name,
        Value,
        Patient_id,
        COUNT(*) AS Instance_Count
    FROM filtered
    GROUP BY Original_table_name, Variable_name, Value, Patient_id
),

-- ── ③ ClassKey 별 집계: 환자 수 / 총 발생 수 ────────────────────────
-- Python: total_num = sum(filtered_values), len(filtered_values) = 환자 수
class_totals AS (
    SELECT
        Original_table_name,
        Variable_name,
        Value,
        COUNT(*)             AS num_patients,   -- 환자 수
        SUM(Instance_Count)  AS total_num       -- 총 발생 수
    FROM class_patient
    GROUP BY Original_table_name, Variable_name, Value
),

-- ── ④ Instance_Count 분포 → 확률 ──────────────────────────────────
-- Python: instance_counter = Counter(filtered_values)
--         prob = count / total_num  (count = 해당 발생 횟수를 가진 환자 수)
instance_counter AS (
    SELECT
        cp.Original_table_name,
        cp.Variable_name,
        cp.Value,
        cp.Instance_Count,
        COUNT(*)              AS patient_count,   -- 이 횟수를 가진 환자 수
        ct.total_num,
        ct.num_patients,
        COUNT(*) * 1.0 / ct.total_num AS prob
    FROM class_patient cp
    JOIN class_totals ct
        ON  cp.Original_table_name = ct.Original_table_name
        AND cp.Variable_name       = ct.Variable_name
        AND cp.Value               = ct.Value
    GROUP BY cp.Original_table_name, cp.Variable_name, cp.Value,
             cp.Instance_Count, ct.total_num, ct.num_patients
),

-- ── ⑤ 최종 다양성 집계 ───────────────────────────────────────────
-- Python: instance_diversity = len(filtered_values) / total_num
--         simpson_diversity_score = 1 - Σp²  (or 1.0 if instance_diversity==1)
diversity_summary AS (
    SELECT
        Original_table_name,
        Variable_name,
        Value,
        ANY_VALUE(num_patients)  AS num_patients,
        ANY_VALUE(total_num)     AS total_num,
        ROUND(
            ANY_VALUE(num_patients) * 100.0 / ANY_VALUE(total_num),
        2) AS "Instance Diversity (%)",
        ROUND(
            CASE
                WHEN ANY_VALUE(num_patients) = ANY_VALUE(total_num)
                    THEN 100.0                          -- 모든 환자 1회 발생
                ELSE (1.0 - SUM(prob * prob)) * 100.0  -- 1 - Σp²
            END,
        2) AS "Gini-Simpson Index (%)"
    FROM instance_counter
    GROUP BY Original_table_name, Variable_name, Value
)

SELECT *
FROM diversity_summary
ORDER BY total_num DESC
