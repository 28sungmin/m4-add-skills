-- ═══════════════════════════════════════════════════════════════════
-- LYDUS Format Validity (DuckDB version, v1.0 260610)
--
-- 참조: LYDUS_Format_Validity.py (이성민 작성)
--       LYDUS 품질관리 프로그램 활용 가이드라인
--
-- 변환 전략
--   ① quiq_codes   : Mapping_info_1 = 'medical_code' 인 행만 추출
--   ② with_via     : VIA 테이블과 LEFT JOIN → Description 추가
--   ③ code_typed   : 변수명/설명 키워드로 코드 타입 판별 (match_code_regex 대응)
--                    7종: ICD-9, ICD-10, ICD-11, SNOMED-CT, RxNorm, LOINC, ATC
--   ④ validated    : regexp_matches() 로 각 값의 형식 검증
--   ⑤ 최종 집계   : (Original_table_name, Variable_name) 별 요약
--
-- < 지원 코드 타입 및 Regex >
--   ICD-9      : ^[0-9]{3}(\.[0-9]{1,2})?$
--   ICD-10     : ^[A-Z]{1}[0-9]{2}(\.[0-9]{1,2})?$
--   ICD-11     : ^[A-Z0-9]{1}[A-Z]{1}[0-9]{1}[A-Z0-9]{1}(\.[A-Z0-9]{1,2})?$
--   SNOMED-CT  : ^[0-9]{6,18}$
--   RxNorm     : ^[0-9]{5,9}$
--   LOINC      : ^[0-9]{1,6}\-[0-9]{1}$
--   ATC        : ^[A-Z]{1}[0-9]{2}[A-Z]{2}[0-9]{2}$
--   Unknown    : Is_valid = NULL (판별 불가)
--
-- < 한계 >
--   LLM fallback 없음. 위 7종 외 코드는 Unknown 처리됨.
--   완전한 검증이 필요하면 scripts/format_validity.py (LLM fallback 포함) 사용.
--
-- < 실행 방법 >
-- Python:
--   import duckdb
--   sql = open('scripts/duckdb.sql').read()
--   sql = sql.replace('{quiq_csv}', '/path/to/quiq.csv')
--   sql = sql.replace('{via_csv}', '/path/to/via.csv')
--   # VIA 없이 실행 시: via_csv 대신 빈 CSV (headers만 있는 파일) 사용
--   df = duckdb.sql(sql).df()
-- ═══════════════════════════════════════════════════════════════════

WITH

-- ── ① medical_code 행 추출 ───────────────────────────────────────
quiq_codes AS (
    SELECT
        Original_table_name,
        Variable_name,
        -- 정수형 float (e.g. 4019.0) → '4019' 로 변환
        CASE
            WHEN regexp_matches(Value::VARCHAR, '^\d+\.0+$')
                THEN regexp_replace(Value::VARCHAR, '\.0+$', '')
            ELSE Value::VARCHAR
        END AS Value
    FROM read_csv_auto('{quiq_csv}')
    WHERE lower(coalesce(Mapping_info_1, '')) LIKE '%medical_code%'
      AND Value IS NOT NULL
),

-- ── ② VIA JOIN → Description 추가 ───────────────────────────────
with_via AS (
    SELECT
        q.Original_table_name,
        q.Variable_name,
        q.Value,
        lower(coalesce(v.Description, '')) AS desc_lower,
        lower(q.Variable_name)             AS name_lower
    FROM quiq_codes q
    LEFT JOIN read_csv_auto('{via_csv}') v
        ON  q.Original_table_name = v.Original_table_name
        AND q.Variable_name       = v.Variable_name
),

-- ── ③ 코드 타입 판별 (match_code_regex 대응) ──────────────────────
code_typed AS (
    SELECT
        *,
        CASE
            WHEN (name_lower LIKE '%icd%' AND name_lower LIKE '%9%')
              OR (desc_lower  LIKE '%icd%' AND desc_lower  LIKE '%9%')
                THEN 'ICD-9'
            WHEN (name_lower LIKE '%icd%' AND name_lower LIKE '%10%')
              OR (desc_lower  LIKE '%icd%' AND desc_lower  LIKE '%10%')
                THEN 'ICD-10'
            WHEN (name_lower LIKE '%icd%' AND name_lower LIKE '%11%')
              OR (desc_lower  LIKE '%icd%' AND desc_lower  LIKE '%11%')
                THEN 'ICD-11'
            WHEN (name_lower LIKE '%snomed%' AND name_lower LIKE '%ct%')
              OR (desc_lower  LIKE '%snomed%' AND desc_lower  LIKE '%ct%')
                THEN 'SNOMED-CT'
            WHEN name_lower LIKE '%rxnorm%' OR desc_lower LIKE '%rxnorm%'
                THEN 'RxNorm'
            WHEN name_lower LIKE '%loinc%' OR desc_lower LIKE '%loinc%'
                THEN 'LOINC'
            WHEN name_lower LIKE '%atc%' OR desc_lower LIKE '%atc%'
                THEN 'ATC'
            ELSE NULL  -- Unknown: LLM fallback 필요
        END AS Code_type
    FROM with_via
),

-- ── ④ Regex 적용 → Is_valid ──────────────────────────────────────
validated AS (
    SELECT
        Original_table_name,
        Variable_name,
        Value,
        Code_type,
        CASE Code_type
            WHEN 'ICD-9'     THEN regexp_matches(Value, '^[0-9]{3}(\.[0-9]{1,2})?$')
            WHEN 'ICD-10'    THEN regexp_matches(Value, '^[A-Z]{1}[0-9]{2}(\.[0-9]{1,2})?$')
            WHEN 'ICD-11'    THEN regexp_matches(Value, '^[A-Z0-9]{1}[A-Z]{1}[0-9]{1}[A-Z0-9]{1}(\.[A-Z0-9]{1,2})?$')
            WHEN 'SNOMED-CT' THEN regexp_matches(Value, '^[0-9]{6,18}$')
            WHEN 'RxNorm'    THEN regexp_matches(Value, '^[0-9]{5,9}$')
            WHEN 'LOINC'     THEN regexp_matches(Value, '^[0-9]{1,6}-[0-9]{1}$')
            WHEN 'ATC'       THEN regexp_matches(Value, '^[A-Z]{1}[0-9]{2}[A-Z]{2}[0-9]{2}$')
            ELSE NULL  -- Unknown: 판별 불가
        END AS Is_valid
    FROM code_typed
)

-- ── ⑤ 변수별 집계 ────────────────────────────────────────────────
SELECT
    Original_table_name,
    Variable_name,
    ANY_VALUE(Code_type)                                       AS Code_type,
    COUNT(*)                                                   AS Total_code,
    COUNT(*) - SUM(CASE WHEN Is_valid THEN 1 ELSE 0 END)      AS Invalid_code,
    ROUND(
        SUM(CASE WHEN Is_valid THEN 1 ELSE 0 END) * 100.0 / COUNT(*),
    2)                                                         AS "Format_Validity (%)",
    COUNT(*) FILTER (WHERE Is_valid IS NULL)                   AS Unknown_code
FROM validated
GROUP BY Original_table_name, Variable_name
ORDER BY Total_code DESC
