-- ═══════════════════════════════════════════════════════════════════
-- LYDUS Class Diversity (DuckDB version, v1.0 260610)
--
-- 참조: class_diversity.py (이성민 작성)
--       LYDUS 품질관리 프로그램 활용 가이드라인
--
-- 변환 전략
--   ① filtered_quiq    : Is_categorical=1, Mapping_info_1 note/code/date 제외
--   ② group_stats      : (Original_table_name, Variable_name) 별 total/class 수
--   ③ class_counts     : 클래스별 빈도
--   ④ class_probs      : 클래스별 확률 (count / total)
--   ⑤ simpson_calc     : Simpson(Σp²), Shannon(-Σp·ln(p)) 다양성 계산
--   ⑥ diversity_summary: 최종 요약 — Class_diversity (%)
--
-- < 실행 방법 >
-- {quiq_csv}: QUIQ CSV 파일 경로 (e.g. '/path/to/quiq_3patients.csv')
--
-- Python:
--   import duckdb
--   sql = open('scripts/duckdb.sql').read().replace('{quiq_csv}', '/path/to/quiq.csv')
--   df = duckdb.sql(sql).df()
--
-- < Class_diversity (%) 계산 공식 >
--   simpson_diversity    = Σ p²           (p = 클래스 빈도 / 전체 수)
--   class_diversity      = class_num / total_num
--   simpson_score:
--     class_num == total_num (모든 값 유일) → 1.0  (Python edge case 일치)
--     otherwise                             → 1 - Σp²
--   Class_diversity (%)  = simpson_score × 100
--
-- < 출력 전환 >
--   기본    : SELECT * FROM diversity_summary   (변수별 요약)
--   상세    : SELECT * FROM class_detail        (클래스별 빈도)
-- ═══════════════════════════════════════════════════════════════════

WITH

-- ── ① 필터링: 범주형 변수만, note/code/date 제외 ─────────────────
-- Python: _filter_categorical()
filtered_quiq AS (
    SELECT
        Original_table_name,
        Variable_name,
        Value
    FROM read_csv_auto('{quiq_csv}')
    WHERE
        NOT regexp_matches(lower(coalesce(Mapping_info_1, '')), '.*(note|code|date).*')
        AND TRY_CAST(Is_categorical AS INTEGER) = 1
        AND Value IS NOT NULL
),

-- ── ② (테이블, 변수) 별 전체 수 / 클래스 수 ────────────────────────
group_stats AS (
    SELECT
        Original_table_name,
        Variable_name,
        COUNT(*)              AS total_num,
        COUNT(DISTINCT Value) AS class_num
    FROM filtered_quiq
    GROUP BY Original_table_name, Variable_name
),

-- ── ③ 클래스별 빈도 ───────────────────────────────────────────────
class_counts AS (
    SELECT
        Original_table_name,
        Variable_name,
        Value    AS class_value,
        COUNT(*) AS class_count
    FROM filtered_quiq
    GROUP BY Original_table_name, Variable_name, Value
),

-- ── ④ 클래스별 확률 ───────────────────────────────────────────────
class_probs AS (
    SELECT
        cc.Original_table_name,
        cc.Variable_name,
        cc.class_value,
        cc.class_count,
        gs.total_num,
        gs.class_num,
        cc.class_count * 1.0 / gs.total_num AS prob
    FROM class_counts cc
    JOIN group_stats gs
        ON cc.Original_table_name = gs.Original_table_name
        AND cc.Variable_name      = gs.Variable_name
),

-- ── ⑤ Simpson / Shannon 다양성 계산 ──────────────────────────────
-- Python: _calculate_diversity()
--   simpson_diversity = sum(prob**2 for prob in probabilities)
--   shannon_diversity = -sum(prob * log(prob) for prob in probabilities)
simpson_calc AS (
    SELECT
        Original_table_name,
        Variable_name,
        total_num,
        class_num,
        SUM(prob * prob)      AS simpson_sum,
        -SUM(prob * LN(prob)) AS shannon_diversity
    FROM class_probs
    GROUP BY Original_table_name, Variable_name, total_num, class_num
),

-- ── ⑥ 최종 요약: Class_diversity (%) ─────────────────────────────
diversity_summary AS (
    SELECT
        Original_table_name,
        Variable_name,
        total_num AS "Total Number of Data",
        class_num AS "Number of Classes",
        ROUND(
            CASE
                WHEN class_num = total_num THEN 100.0     -- 모든 값 유일 → 1.0
                ELSE (1.0 - simpson_sum) * 100.0          -- 1 - Σp²
            END,
        2) AS "Class_diversity (%)"
    FROM simpson_calc
),

-- ── ⑦ 클래스별 상세 빈도 (dict_variable_counts 대응) ──────────────
class_detail AS (
    SELECT
        Original_table_name,
        Variable_name,
        class_value             AS "Class",
        class_count             AS "Count",
        ROUND(prob * 100.0, 2)  AS "Proportion (%)"
    FROM class_probs
)

-- ── 출력: diversity_summary (기본) ───────────────────────────────
-- 상세 클래스 빈도 조회 시 아래를 변경:
--   SELECT * FROM class_detail
--   ORDER BY Original_table_name, Variable_name, "Count" DESC
SELECT *
FROM diversity_summary
ORDER BY "Total Number of Data" DESC
