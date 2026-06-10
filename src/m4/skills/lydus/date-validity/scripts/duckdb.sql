-- ═══════════════════════════════════════════════════════════════════
-- LYDUS Date Validity (DuckDB version, v1.0 260610)
--
-- 참조: LYDUS_Date_Validity.py (이성민 작성)
--       LYDUS 품질관리 프로그램 활용 가이드라인
--
-- 변환 전략
--   ① date_data      : QUIQ에서 날짜 관련 데이터 추출
--                       - Event_date 컬럼 (non-null)
--                       - Mapping_info_1 = 'date' 인 행의 Value
--   ② validated      : 각 날짜 문자열의 유효성 판별
--                       - TRY_STRPTIME 으로 표준 형식 7종 시도
--                       - 한국어 날짜 형식 (YYYY년 MM월 DD일) 은 regex 로 처리
--                       - ※ LLM fallback 없음 — 모호한 문자열은 invalid 처리
--   ③ summary        : (Original_table_name, Variable_name) 별 집계
--
-- < 실행 방법 >
-- Python:
--   import duckdb
--   sql = open('scripts/duckdb.sql').read().replace('{quiq_csv}', '/path/to/quiq.csv')
--   df = duckdb.sql(sql).df()
--
-- < 출력 컬럼 >
--   Original_table_name, Variable_name, Total_date, Invalid_date, Date_Validity (%)
--
-- < 주의 >
--   LLM fallback 이 없으므로 희귀 형식(한문, 약어 등) 날짜는 invalid 로 분류됨.
--   완전한 검증이 필요하면 scripts/date_validity.py (LLM fallback 포함) 사용.
-- ═══════════════════════════════════════════════════════════════════

WITH

-- ── ① 날짜 데이터 추출 ──────────────────────────────────────────────
-- Python: _extract_date_data_mapping()
date_data AS (
    -- Event_date 컬럼
    SELECT
        Original_table_name,
        'Event_date'   AS Variable_name,
        Event_date::VARCHAR AS Date_value
    FROM read_csv_auto('{quiq_csv}')
    WHERE Event_date IS NOT NULL

    UNION ALL

    -- Mapping_info_1 = 'date' 인 행의 Value
    SELECT
        Original_table_name,
        Variable_name,
        Value::VARCHAR AS Date_value
    FROM read_csv_auto('{quiq_csv}')
    WHERE regexp_matches(lower(coalesce(Mapping_info_1, '')), '.*date.*')
      AND Value IS NOT NULL
),

-- ── ② 유효성 판별 ────────────────────────────────────────────────────
-- Python: _is_valid_date() + _valid_date_custom()
--   표준 7종 + 한국어 날짜 형식 (LLM fallback 없음)
validated AS (
    SELECT
        Original_table_name,
        Variable_name,
        Date_value,
        (
            -- ISO / 일반 형식
            TRY_STRPTIME(Date_value, '%Y-%m-%d %H:%M:%S') IS NOT NULL
            OR TRY_STRPTIME(Date_value, '%Y-%m-%d')        IS NOT NULL
            OR TRY_STRPTIME(Date_value, '%Y/%m/%d')        IS NOT NULL
            OR TRY_STRPTIME(Date_value, '%d/%m/%Y')        IS NOT NULL
            OR TRY_STRPTIME(Date_value, '%m/%d/%Y')        IS NOT NULL
            OR TRY_STRPTIME(Date_value, '%Y-%m-%dT%H:%M:%S') IS NOT NULL
            OR TRY_STRPTIME(Date_value, '%d-%m-%Y')        IS NOT NULL
            -- 한국어 날짜: YYYY년 MM월 DD일 (공백 포함 허용)
            OR regexp_matches(Date_value,
                '^\d{4}년\s*\d{1,2}월\s*\d{1,2}일?$')
        ) AS is_valid
    FROM date_data
)

-- ── ③ 변수별 집계 ─────────────────────────────────────────────────
SELECT
    Original_table_name,
    Variable_name,
    COUNT(*)                                               AS Total_date,
    COUNT(*) - SUM(CASE WHEN is_valid THEN 1 ELSE 0 END)  AS Invalid_date,
    ROUND(
        SUM(CASE WHEN is_valid THEN 1 ELSE 0 END) * 100.0 / COUNT(*),
    2) AS "Date_Validity (%)"
FROM validated
GROUP BY Original_table_name, Variable_name
ORDER BY Total_date DESC
