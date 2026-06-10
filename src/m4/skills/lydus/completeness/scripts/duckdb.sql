-- ═══════════════════════════════════════════════════════════════════
-- LYDUS Completeness (DuckDB version, v1.0 260610)
--
-- 참조: LYDUS_Completeness.py (이성민 작성)
--       LYDUS 품질관리 프로그램 활용 가이드라인
--
-- 변환 전략
--   ① completeness_per_variable : (Original_table_name, Variable_name) 별
--        COUNT(*)       → Total_num  (전체 행 수)
--        COUNT(Value)   → NonNull_num (Value가 NULL이 아닌 행 수)
--        Null_num       → Total_num - NonNull_num
--        Completeness   → NonNull_num / Total_num * 100
--
-- < 실행 방법 >
-- {quiq_csv}: QUIQ CSV 파일 경로 (e.g. '/path/to/quiq_3patients.csv')
--
-- Python:
--   import duckdb
--   sql = open('scripts/duckdb.sql').read().replace('{quiq_csv}', '/path/to/quiq.csv')
--   df = duckdb.sql(sql).df()
--
-- < 출력 컬럼 >
--   Original_table_name, Variable_name,
--   Total_num, Null_num, Completeness (%)
-- ═══════════════════════════════════════════════════════════════════

WITH completeness_per_variable AS (
    SELECT
        Original_table_name,
        Variable_name,
        COUNT(*)            AS Total_num,
        COUNT(*) - COUNT(Value) AS Null_num,
        ROUND(COUNT(Value) * 100.0 / COUNT(*), 2) AS "Completeness (%)"
    FROM read_csv_auto('{quiq_csv}')
    GROUP BY Original_table_name, Variable_name
)

SELECT *
FROM completeness_per_variable
ORDER BY Total_num DESC
