-- ═══════════════════════════════════════════════════════════════════
-- MIMIC-IV → QUIQ Table (BigQuery version, v5 260527)
--
-- 참조: MIMICIV_to_QUIQ_colab_3.py, QUIQ_MIMICIV.sql
--       품질관리 프로그램 활용 가이드라인 제4권 §1.5~§1.6
--
-- 변환 전략
--   ① Wide  테이블 (admissions, patients 등) : BigQuery UNPIVOT
--   ② Code  테이블 (diagnoses_icd, procedures_icd) : 코드+제목 행 분리
--   ③ Event 테이블 (labevents, chartevents 등) : base+all CTE 패턴
--
-- < 실행 방법 (M4 MCP) >
-- execute_query(sql)  # 전체 쿼리를 문자열로 전달
-- BigQuery 스크립트 모드: CREATE TEMP FUNCTION + SELECT
--
-- < CSV 저장 방법 >
-- ① GCS로 직접 내보내기 (EXPORT DATA):
--      EXPORT DATA OPTIONS (
--          uri='gs://<버킷명>/quiq_mimiciv_*.csv',
--          format='CSV', overwrite=true, header=true
--      ) AS <이 쿼리 전체>;
--
-- ② BigQuery 테이블 경유 후 내보내기:
--      CREATE OR REPLACE TABLE `<프로젝트>.<데이터셋>.quiq_mimiciv` AS <이 쿼리>;
--      -- 이후 콘솔 → 테이블 → 내보내기 → CSV / GCS 선택
--
-- ③ M4 MCP에서 CSV로 저장 (권장):
--      from google.cloud import bigquery
--      import pandas as pd
--      client = bigquery.Client()
--      df = client.query(SQL).to_dataframe()
--      df.to_csv('quiq_mimiciv.csv', index=False, encoding='utf-8-sig')
--
-- < Mapping rule 기준 (가이드라인 §1.5.2) >
--   Rule 3: 코드     → medical_code / null
--   Rule 4: 이벤트   → event / lab_event|chart_event|null
--   Rule 5: 날짜     → date / null
--   Rule 6: 진단명   → diagnosis / null
--   Rule 7: 처방     → prescription / drug|prescription_info|null
--   Rule 8: 처치     → procedure / null
-- ═══════════════════════════════════════════════════════════════════

-- ── BigQuery TEMP FUNCTION (DuckDB macro 대체) ────────────────────
CREATE TEMP FUNCTION _var_type(val STRING)
RETURNS STRING AS (
    CASE
        WHEN val IS NULL OR val = ''
            THEN ''
        WHEN SAFE.PARSE_TIMESTAMP('%Y-%m-%d %H:%M:%S', val) IS NOT NULL
            THEN 'timestamp'
        WHEN SAFE.PARSE_TIMESTAMP('%Y-%m-%dT%H:%M:%S', val) IS NOT NULL
            THEN 'timestamp'
        WHEN SAFE.PARSE_DATE('%Y-%m-%d', val) IS NOT NULL
            THEN 'timestamp'
        WHEN SAFE_CAST(val AS FLOAT64) IS NOT NULL
            THEN 'numeric'
        ELSE 'string'
    END
);

CREATE TEMP FUNCTION _is_cat(col STRING)
RETURNS STRING AS (
    CASE WHEN col IN (
        'gender','race','admission_type','admission_location','discharge_location',
        'insurance','language','marital_status','hospital_expire_flag',
        'eventtype','careunit','drg_type','event_txt','drug_type','proc_type',
        'status','route','frequency','infusion_type','sliding_scale','priority',
        'flag','interpretation','order_type','order_subtype','transaction_type',
        'order_status','arrival_transport','disposition','rhythm','acuity',
        'icd_version','icd_code','hcpcs_cd','curr_service','prev_service',
        'first_careunit','last_careunit','statusdescription','param_type',
        'barcode_type','complete_dose_not_given','will_remainder_be_given',
        'new_iv_bag_hung','continued_infusion_in_other_location','infusion_complete',
        'non_formulary_visual_verification','spec_type_desc','ab_name',
        'sex','linksto','category','fluid',
        'administration_type',
        'gsn','ndc','etccode'
    ) THEN '1' ELSE '0' END
);

WITH

-- ════════════════════════════════════════════════════════════════════
-- ① WIDE 테이블 (UNPIVOT)
--    날짜/시간 컬럼은 Value에 기록, Event_date = NULL (가이드라인 §1.5.5 유의사항 1)
-- ════════════════════════════════════════════════════════════════════

-- ── hosp.admissions ──────────────────────────────────────────────
t_admissions AS (
    SELECT ROW_NUMBER() OVER (ORDER BY subject_id) - 1 AS _pk,
        subject_id, hadm_id,
        COALESCE(CAST(admittime          AS STRING), '') AS admittime,
        COALESCE(CAST(dischtime          AS STRING), '') AS dischtime,
        COALESCE(CAST(deathtime          AS STRING), '') AS deathtime,
        COALESCE(CAST(admission_type     AS STRING), '') AS admission_type,
        COALESCE(CAST(admission_location AS STRING), '') AS admission_location,
        COALESCE(CAST(discharge_location AS STRING), '') AS discharge_location,
        COALESCE(CAST(insurance          AS STRING), '') AS insurance,
        COALESCE(CAST(`language`         AS STRING), '') AS `language`,
        COALESCE(CAST(marital_status     AS STRING), '') AS marital_status,
        COALESCE(CAST(race               AS STRING), '') AS race,
        COALESCE(CAST(edregtime          AS STRING), '') AS edregtime,
        COALESCE(CAST(edouttime          AS STRING), '') AS edouttime,
        COALESCE(CAST(hospital_expire_flag AS STRING), '') AS hospital_expire_flag
    FROM `physionet-data`.mimiciv_3_1_hosp.admissions
),
u_admissions AS (
    SELECT * FROM t_admissions
    UNPIVOT (raw_val FOR Variable_name IN (admittime, dischtime, deathtime, admission_type, admission_location,
       discharge_location, insurance, `language`, marital_status, race,
       edregtime, edouttime, hospital_expire_flag
    ))
),

-- ── hosp.patients ────────────────────────────────────────────────
-- §1.5.3: Python 코드 기준 5개 컬럼 (anchor_year_group 포함)
-- §1.5.2 Mapping rule 5: dod → Mapping_info_1 = 'date'
t_patients AS (
    SELECT ROW_NUMBER() OVER (ORDER BY subject_id) - 1 AS _pk,
        subject_id,
        COALESCE(CAST(gender           AS STRING), '') AS gender,
        COALESCE(CAST(anchor_age       AS STRING), '') AS anchor_age,
        COALESCE(CAST(anchor_year      AS STRING), '') AS anchor_year,
        COALESCE(CAST(anchor_year_group AS STRING), '') AS anchor_year_group,
        COALESCE(CAST(dod              AS STRING), '') AS dod
    FROM `physionet-data`.mimiciv_3_1_hosp.patients
),
u_patients AS (
    SELECT * FROM t_patients
    UNPIVOT (raw_val FOR Variable_name IN (gender, anchor_age, anchor_year, anchor_year_group, dod))
),

-- ── hosp.transfers ───────────────────────────────────────────────
t_transfers AS (
    SELECT ROW_NUMBER() OVER (ORDER BY subject_id) - 1 AS _pk,
        subject_id, hadm_id,
        COALESCE(CAST(eventtype AS STRING), '') AS eventtype,
        COALESCE(CAST(careunit  AS STRING), '') AS careunit,
        COALESCE(CAST(intime    AS STRING), '') AS intime,
        COALESCE(CAST(outtime   AS STRING), '') AS outtime
    FROM `physionet-data`.mimiciv_3_1_hosp.transfers
),
u_transfers AS (
    SELECT * FROM t_transfers
    UNPIVOT (raw_val FOR Variable_name IN (eventtype, careunit, intime, outtime))
),

-- ── hosp.omr ─────────────────────────────────────────────────────
t_omr AS (
    SELECT ROW_NUMBER() OVER (ORDER BY subject_id) - 1 AS _pk,
        subject_id,
        CAST(chartdate AS STRING)                   AS _ev,
        COALESCE(CAST(seq_num      AS STRING), '') AS seq_num,
        COALESCE(CAST(result_name  AS STRING), '') AS result_name,
        COALESCE(CAST(result_value AS STRING), '') AS result_value
    FROM `physionet-data`.mimiciv_3_1_hosp.omr
),
u_omr AS (
    SELECT * FROM t_omr
    UNPIVOT (raw_val FOR Variable_name IN (seq_num, result_name, result_value))
),

-- ── hosp.drgcodes ────────────────────────────────────────────────
t_drgcodes AS (
    SELECT ROW_NUMBER() OVER (ORDER BY subject_id) - 1 AS _pk,
        subject_id, hadm_id,
        COALESCE(CAST(drg_type      AS STRING), '') AS drg_type,
        COALESCE(CAST(drg_code      AS STRING), '') AS drg_code,
        COALESCE(CAST(description   AS STRING), '') AS description,
        COALESCE(CAST(drg_severity  AS STRING), '') AS drg_severity,
        COALESCE(CAST(drg_mortality AS STRING), '') AS drg_mortality
    FROM `physionet-data`.mimiciv_3_1_hosp.drgcodes
),
u_drgcodes AS (
    SELECT * FROM t_drgcodes
    UNPIVOT (raw_val FOR Variable_name IN (drg_type, drg_code, description, drg_severity, drg_mortality))
),

-- ── hosp.emar ────────────────────────────────────────────────────
t_emar AS (
    SELECT ROW_NUMBER() OVER (ORDER BY subject_id) - 1 AS _pk,
        subject_id, hadm_id,
        CAST(charttime AS STRING)                      AS _ev,
        COALESCE(CAST(emar_seq    AS STRING), '') AS emar_seq,
        COALESCE(CAST(medication  AS STRING), '') AS medication,
        COALESCE(CAST(event_txt   AS STRING), '') AS event_txt,
        COALESCE(CAST(scheduletime AS STRING), '') AS scheduletime,
        COALESCE(CAST(storetime   AS STRING), '') AS storetime
    FROM `physionet-data`.mimiciv_3_1_hosp.emar
),
u_emar AS (
    SELECT * FROM t_emar
    UNPIVOT (raw_val FOR Variable_name IN (emar_seq, medication, event_txt, scheduletime, storetime))
),

-- ── hosp.emar_detail ─────────────────────────────────────────────
t_emar_detail AS (
    SELECT ROW_NUMBER() OVER (ORDER BY subject_id) - 1 AS _pk,
        subject_id,
        dose_due_unit AS _du, dose_given_unit AS _dgu,
        product_unit  AS _pu, infusion_rate_unit AS _iru,
        COALESCE(CAST(emar_seq                          AS STRING), '') AS emar_seq,
        COALESCE(CAST(parent_field_ordinal              AS STRING), '') AS parent_field_ordinal,
        COALESCE(CAST(administration_type               AS STRING), '') AS administration_type,
        COALESCE(CAST(barcode_type                      AS STRING), '') AS barcode_type,
        COALESCE(CAST(reason_for_no_barcode             AS STRING), '') AS reasons_for_no_barcode,
        COALESCE(CAST(complete_dose_not_given           AS STRING), '') AS complete_dose_not_given,
        COALESCE(CAST(dose_due                          AS STRING), '') AS dose_due,
        COALESCE(CAST(dose_given                        AS STRING), '') AS dose_given,
        COALESCE(CAST(will_remainder_of_dose_be_given   AS STRING), '') AS will_remainder_be_given,
        COALESCE(CAST(product_amount_given              AS STRING), '') AS product_amount_given,
        COALESCE(CAST(product_code                      AS STRING), '') AS product_code,
        COALESCE(CAST(product_description               AS STRING), '') AS product_description,
        COALESCE(CAST(product_description_other         AS STRING), '') AS product_description_other,
        COALESCE(CAST(prior_infusion_rate               AS STRING), '') AS prior_infusion_rate,
        COALESCE(CAST(infusion_rate                     AS STRING), '') AS infusion_rate,
        COALESCE(CAST(infusion_rate_adjustment          AS STRING), '') AS infusion_rate_adjustment,
        COALESCE(CAST(infusion_rate_adjustment_amount   AS STRING), '') AS infusion_rate_adjustment_amount,
        COALESCE(CAST(`route`                           AS STRING), '') AS `route`,
        COALESCE(CAST(infusion_complete                 AS STRING), '') AS infusion_complete,
        COALESCE(CAST(completion_interval               AS STRING), '') AS completion_interval,
        COALESCE(CAST(new_iv_bag_hung                   AS STRING), '') AS new_iv_bag_hung,
        COALESCE(CAST(continued_infusion_in_other_location AS STRING), '') AS continued_infusion_in_other_location,
        COALESCE(CAST(restart_interval                  AS STRING), '') AS restart_interval,
        COALESCE(CAST(side                              AS STRING), '') AS side,
        COALESCE(CAST(`site`                            AS STRING), '') AS `site`,
        COALESCE(CAST(non_formulary_visual_verification AS STRING), '') AS non_formulary_visual_verification
    FROM `physionet-data`.mimiciv_3_1_hosp.emar_detail
),
u_emar_detail AS (
    SELECT * FROM t_emar_detail
    UNPIVOT (raw_val FOR Variable_name IN (emar_seq, parent_field_ordinal, administration_type, barcode_type,
       reasons_for_no_barcode, complete_dose_not_given, dose_due, dose_given,
       will_remainder_be_given, product_amount_given, product_code, product_description,
       product_description_other, prior_infusion_rate, infusion_rate,
       infusion_rate_adjustment, infusion_rate_adjustment_amount, `route`, infusion_complete,
       completion_interval, new_iv_bag_hung, continued_infusion_in_other_location,
       restart_interval, side, `site`, non_formulary_visual_verification
    ))
),

-- ── hosp.hcpcsevents ─────────────────────────────────────────────
t_hcpcsevents AS (
    SELECT ROW_NUMBER() OVER (ORDER BY subject_id) - 1 AS _pk,
        subject_id, hadm_id,
        CAST(chartdate AS STRING)                        AS _ev,
        COALESCE(CAST(hcpcs_cd         AS STRING), '') AS hcpcs_cd,
        COALESCE(CAST(seq_num          AS STRING), '') AS seq_num,
        COALESCE(CAST(short_description AS STRING), '') AS short_description
    FROM `physionet-data`.mimiciv_3_1_hosp.hcpcsevents
),
u_hcpcsevents AS (
    SELECT * FROM t_hcpcsevents
    UNPIVOT (raw_val FOR Variable_name IN (hcpcs_cd, seq_num, short_description))
),

-- ── hosp.microbiologyevents ──────────────────────────────────────
t_micro AS (
    SELECT ROW_NUMBER() OVER (ORDER BY subject_id) - 1 AS _pk,
        subject_id, hadm_id,
        -- charttime 우선, 없으면 chartdate (행으로는 표현 안 함)
        COALESCE(CAST(charttime AS STRING), CAST(chartdate AS STRING)) AS _ev,
        COALESCE(CAST(spec_type_desc     AS STRING), '') AS spec_type_desc,
        COALESCE(CAST(test_seq           AS STRING), '') AS test_seq,
        COALESCE(CAST(storedate          AS STRING), '') AS storedate,
        COALESCE(CAST(storetime          AS STRING), '') AS storetime,
        COALESCE(CAST(test_name          AS STRING), '') AS test_name,
        COALESCE(CAST(org_name           AS STRING), '') AS org_name,
        COALESCE(CAST(isolate_num        AS STRING), '') AS isolate_num,
        COALESCE(CAST(quantity           AS STRING), '') AS quantity,
        COALESCE(CAST(ab_name            AS STRING), '') AS ab_name,
        COALESCE(CAST(dilution_text      AS STRING), '') AS dilution_text,
        COALESCE(CAST(dilution_comparison AS STRING), '') AS dilution_comparison,
        COALESCE(CAST(dilution_value     AS STRING), '') AS dilution_value,
        COALESCE(CAST(interpretation     AS STRING), '') AS interpretation,
        COALESCE(CAST(comments           AS STRING), '') AS comments
    FROM `physionet-data`.mimiciv_3_1_hosp.microbiologyevents
),
u_micro AS (
    SELECT * FROM t_micro
    UNPIVOT (raw_val FOR Variable_name IN (spec_type_desc, test_seq,
       storedate, storetime, test_name, org_name,
       isolate_num, quantity, ab_name, dilution_text,
       dilution_comparison, dilution_value, interpretation, comments
    ))
),

-- ── hosp.pharmacy ────────────────────────────────────────────────
t_pharmacy AS (
    SELECT ROW_NUMBER() OVER (ORDER BY subject_id) - 1 AS _pk,
        subject_id, hadm_id,
        CAST(starttime      AS STRING) AS _ev,
        CAST(expirationdate AS STRING) AS _expdate,
        duration_interval AS _dur_int,
        expiration_unit   AS _exp_unit,
        COALESCE(CAST(starttime       AS STRING), '') AS starttime,
        COALESCE(CAST(stoptime        AS STRING), '') AS stoptime,
        COALESCE(CAST(medication      AS STRING), '') AS medication,
        COALESCE(CAST(proc_type       AS STRING), '') AS proc_type,
        COALESCE(CAST(`status`        AS STRING), '') AS `status`,
        COALESCE(CAST(entertime       AS STRING), '') AS entertime,
        COALESCE(CAST(verifiedtime    AS STRING), '') AS verifiedtime,
        COALESCE(CAST(`route`         AS STRING), '') AS `route`,
        COALESCE(CAST(frequency       AS STRING), '') AS frequency,
        COALESCE(CAST(disp_sched      AS STRING), '') AS disp_sched,
        COALESCE(CAST(infusion_type   AS STRING), '') AS infusion_type,
        COALESCE(CAST(sliding_scale   AS STRING), '') AS sliding_scale,
        COALESCE(CAST(lockout_interval AS STRING), '') AS lockout_interval,
        COALESCE(CAST(basal_rate      AS STRING), '') AS basal_rate,
        COALESCE(CAST(one_hr_max      AS STRING), '') AS one_hr_max,
        COALESCE(CAST(doses_per_24_hrs AS STRING), '') AS doses_per_24_hrs,
        COALESCE(CAST(duration        AS STRING), '') AS duration,
        COALESCE(CAST(expiration_value AS STRING), '') AS expiration_value,
        COALESCE(CAST(expirationdate  AS STRING), '') AS expirationdate,
        COALESCE(CAST(dispensation    AS STRING), '') AS dispensation,
        COALESCE(CAST(fill_quantity   AS STRING), '') AS fill_quantity
    FROM `physionet-data`.mimiciv_3_1_hosp.pharmacy
),
u_pharmacy AS (
    SELECT * FROM t_pharmacy
    UNPIVOT (raw_val FOR Variable_name IN (starttime, stoptime, medication, proc_type, `status`, entertime, verifiedtime,
       `route`, frequency, disp_sched, infusion_type, sliding_scale, lockout_interval,
       basal_rate, one_hr_max, doses_per_24_hrs, duration,
       expiration_value, expirationdate, dispensation, fill_quantity
    ))
),

-- ── hosp.poe ─────────────────────────────────────────────────────
t_poe AS (
    SELECT ROW_NUMBER() OVER (ORDER BY subject_id) - 1 AS _pk,
        subject_id, hadm_id,
        CAST(ordertime AS STRING)                        AS _ev,
        COALESCE(CAST(poe_seq          AS STRING), '') AS poe_seq,
        COALESCE(CAST(order_type       AS STRING), '') AS order_type,
        COALESCE(CAST(order_subtype    AS STRING), '') AS order_subtype,
        COALESCE(CAST(transaction_type AS STRING), '') AS transaction_type,
        COALESCE(CAST(order_status     AS STRING), '') AS order_status
    FROM `physionet-data`.mimiciv_3_1_hosp.poe
),
u_poe AS (
    SELECT * FROM t_poe
    UNPIVOT (raw_val FOR Variable_name IN (poe_seq, order_type, order_subtype, transaction_type, order_status))
),

-- ── hosp.poe_detail ──────────────────────────────────────────────
t_poe_detail AS (
    SELECT ROW_NUMBER() OVER (ORDER BY subject_id) - 1 AS _pk,
        subject_id,
        COALESCE(CAST(poe_seq     AS STRING), '') AS poe_seq,
        COALESCE(CAST(field_name  AS STRING), '') AS field_name,
        COALESCE(CAST(field_value AS STRING), '') AS field_value
    FROM `physionet-data`.mimiciv_3_1_hosp.poe_detail
),
u_poe_detail AS (
    SELECT * FROM t_poe_detail
    UNPIVOT (raw_val FOR Variable_name IN (poe_seq, field_name, field_value))
),

-- ── hosp.prescriptions ───────────────────────────────────────────
t_prescriptions AS (
    SELECT ROW_NUMBER() OVER (ORDER BY subject_id) - 1 AS _pk,
        subject_id, hadm_id,
        CAST(starttime AS STRING) AS _ev,
        dose_unit_rx   AS _duru,
        form_unit_disp AS _fudu,
        COALESCE(CAST(poe_seq          AS STRING), '') AS poe_seq,
        COALESCE(CAST(starttime        AS STRING), '') AS starttime,
        COALESCE(CAST(stoptime         AS STRING), '') AS stoptime,
        COALESCE(CAST(drug_type        AS STRING), '') AS drug_type,
        COALESCE(CAST(drug             AS STRING), '') AS drug,
        COALESCE(CAST(formulary_drug_cd AS STRING), '') AS formulary_drug_cd,
        COALESCE(CAST(gsn              AS STRING), '') AS gsn,
        COALESCE(CAST(ndc              AS STRING), '') AS ndc,
        COALESCE(CAST(prod_strength    AS STRING), '') AS prod_strength,
        COALESCE(CAST(form_rx          AS STRING), '') AS form_rx,
        COALESCE(CAST(dose_val_rx      AS STRING), '') AS dose_val_rx,
        COALESCE(CAST(form_val_disp    AS STRING), '') AS form_val_disp,
        COALESCE(CAST(doses_per_24_hrs AS STRING), '') AS doses_per_24_hrs,
        COALESCE(CAST(`route`          AS STRING), '') AS `route`
    FROM `physionet-data`.mimiciv_3_1_hosp.prescriptions
),
u_prescriptions AS (
    SELECT * FROM t_prescriptions
    UNPIVOT (raw_val FOR Variable_name IN (poe_seq, starttime, stoptime, drug_type, drug, formulary_drug_cd,
       gsn, ndc, prod_strength, form_rx, dose_val_rx, form_val_disp,
       doses_per_24_hrs, `route`
    ))
),

-- ── hosp.services ────────────────────────────────────────────────
t_services AS (
    SELECT ROW_NUMBER() OVER (ORDER BY subject_id) - 1 AS _pk,
        subject_id, hadm_id,
        COALESCE(CAST(transfertime  AS STRING), '') AS transfertime,
        COALESCE(CAST(prev_service  AS STRING), '') AS prev_service,
        COALESCE(CAST(curr_service  AS STRING), '') AS curr_service
    FROM `physionet-data`.mimiciv_3_1_hosp.services
),
u_services AS (
    SELECT * FROM t_services
    UNPIVOT (raw_val FOR Variable_name IN (transfertime, prev_service, curr_service))
),
-- ════════════════════════════════════════════════════════════════════
-- ② CODE 테이블 (JOIN + 2행 방식)
--    원본 1행 → 2 QUIQ 행 (동일 Primary_key 공유)
--    §1.5.2 Mapping rule 3: icd_code → 'medical_code'
--    §1.5.2 Mapping rule 6: long_title(진단명) → 'diagnosis'
--    §1.5.2 Mapping rule 8: long_title(처치명) → 'procedure'
-- ════════════════════════════════════════════════════════════════════

-- ── hosp.diagnoses_icd ───────────────────────────────────────────
t_diagnoses_icd AS (
    SELECT ROW_NUMBER() OVER (ORDER BY subject_id, hadm_id, seq_num) - 1 AS _pk,
        subject_id, hadm_id,
        COALESCE(CAST(seq_num     AS STRING), '') AS seq_num,
        COALESCE(CAST(icd_code    AS STRING), '') AS icd_code,
        COALESCE(CAST(icd_version AS STRING), '') AS icd_version
    FROM `physionet-data`.mimiciv_3_1_hosp.diagnoses_icd
),
u_diagnoses_icd AS (
    SELECT * FROM t_diagnoses_icd
    UNPIVOT (raw_val FOR Variable_name IN (seq_num, icd_code, icd_version))
),

-- ── hosp.procedures_icd ──────────────────────────────────────────
t_procedures_icd AS (
    SELECT ROW_NUMBER() OVER (ORDER BY subject_id, hadm_id, seq_num) - 1 AS _pk,
        subject_id, hadm_id,
        CAST(chartdate AS STRING)                    AS _ev,
        COALESCE(CAST(seq_num     AS STRING), '') AS seq_num,
        COALESCE(CAST(icd_code    AS STRING), '') AS icd_code,
        COALESCE(CAST(icd_version AS STRING), '') AS icd_version
    FROM `physionet-data`.mimiciv_3_1_hosp.procedures_icd
),
u_procedures_icd AS (
    SELECT * FROM t_procedures_icd
    UNPIVOT (raw_val FOR Variable_name IN (seq_num, icd_code, icd_version))
),
-- ════════════════════════════════════════════════════════════════════
-- ③ EVENT 테이블 - labevents (JOIN + label 방식)
--    §1.5.3: Variable_name = d_labitems.label + '_' + fluid (실제 검사항목명)
--    §1.5.5: Event_date = charttime (측정 시각)
--    §1.6  : 가이드라인 변환 예시 - Creatinine, Hemoglobin 등이 Variable_name
--    Mapping rule 4: Mapping_info_1='event', Mapping_info_2='lab_event'
--
--    원본 1행 → 최대 7 QUIQ 행 (동일 Primary_key 공유)
--      ① 메인 측정값  : Variable_name=label_fluid, Event_date=charttime
--      ② storetime    : Variable_name='storetime',       Mapping_info_1='date'
--      ③ ref_range_lower : Variable_name='ref_range_lower'
--      ④ ref_range_upper : Variable_name='ref_range_upper'
--      ⑤ flag         : Variable_name='flag',            Is_categorical='1'
--      ⑥ lab_priority : Variable_name='lab_priority',    Is_categorical='1'
--      ⑦ comments     : Variable_name='comments'
--
--    subject_id 기준 정렬: _pk를 subject_id 순으로 부여 후
--    q_labevents_all 내 ORDER BY + LIMIT ALL 로 같은 환자 행이 인접하도록 보장
-- ════════════════════════════════════════════════════════════════════

-- ── hosp.labevents (base) ────────────────────────────────────────
-- 원본 테이블을 JOIN하여 필요한 컬럼을 모두 포함한 중간 테이블 생성
q_labevents_base AS (
    SELECT
        ROW_NUMBER() OVER (ORDER BY le.subject_id, le.hadm_id, le.charttime) - 1 AS _pk,
        le.subject_id, le.hadm_id,
        CAST(le.itemid AS STRING)                                    AS _itemid,
        COALESCE(di.label || '_' || di.fluid, di.label,
                 CAST(le.itemid AS STRING))                          AS _var_name,
        CAST(le.charttime AS STRING)                                 AS _ev,
        CAST(le.valueuom  AS STRING)                                 AS _vu,
        COALESCE(
            CASE WHEN le.valuenum IS NOT NULL
                 THEN CAST(le.valuenum AS STRING) END,
            CAST(le.`value` AS STRING)
        )                                                              AS _val,
        CASE WHEN le.valuenum IS NOT NULL THEN 'numeric'
             ELSE _var_type(CAST(le.`value` AS STRING)) END          AS _vtype,
        COALESCE(CAST(le.valuenum        AS STRING), '') AS _valuenum,
        COALESCE(CAST(le.storetime       AS STRING), '') AS _storetime,
        COALESCE(CAST(le.ref_range_lower AS STRING), '') AS _ref_lower,
        COALESCE(CAST(le.ref_range_upper AS STRING), '') AS _ref_upper,
        COALESCE(CAST(le.flag               AS STRING), '') AS _flag,
        COALESCE(CAST(le.`priority`         AS STRING), '') AS _priority,
        COALESCE(CAST(le.comments           AS STRING), '') AS _comments,
        COALESCE(CAST(le.order_provider_id  AS STRING), '') AS _order_provider_id
    FROM `physionet-data`.mimiciv_3_1_hosp.labevents le
    LEFT JOIN `physionet-data`.mimiciv_3_1_hosp.d_labitems di ON le.itemid = di.itemid
),

-- ── hosp.labevents (long: 7컬럼 전개, subject_id 정렬) ───────────
-- base의 컬럼들을 "행으로 분해"
-- LIMIT ALL: DuckDB에서 ORDER BY 결과를 보장하기 위해 명시
q_labevents_all AS (
    -- ① value (메인 측정값)
    SELECT _pk, subject_id, hadm_id, _itemid,
           _var_name AS _vname, _ev, _vu, _val, _vtype,
           '0' AS _iscat, 'event' AS _m1, 'lab_event' AS _m2, 1 AS _rtype
    FROM q_labevents_base
    UNION ALL
    -- ② storetime
    SELECT _pk, subject_id, hadm_id, \'\',
           'storetime', NULL, NULL, _storetime, _var_type(_storetime),
           '0', 'date', NULL, 2
    FROM q_labevents_base
    UNION ALL
    -- ③ valuenum
    SELECT _pk, subject_id, hadm_id, \'\',
           'valuenum', _ev, _vu, _valuenum, _var_type(_valuenum),
           '0', 'event', 'lab_event', 3
    FROM q_labevents_base
    UNION ALL
    -- ④ ref_range_lower
    SELECT _pk, subject_id, hadm_id, \'\',
           'ref_range_lower', NULL, _vu, _ref_lower, _var_type(_ref_lower),
           '0', NULL, NULL, 4
    FROM q_labevents_base
    UNION ALL
    -- ⑤ ref_range_upper
    SELECT _pk, subject_id, hadm_id, \'\',
           'ref_range_upper', NULL, _vu, _ref_upper, _var_type(_ref_upper),
           '0', NULL, NULL, 5
    FROM q_labevents_base
    UNION ALL
    -- ⑥ flag
    SELECT _pk, subject_id, hadm_id, \'\',
           'flag', _ev, NULL, _flag, 'string',
           '1', NULL, NULL, 6
    FROM q_labevents_base
    UNION ALL
    -- ⑦ priority
    SELECT _pk, subject_id, hadm_id, \'\',
           'priority', NULL, NULL, _priority, 'string',
           '1', NULL, NULL, 7
    FROM q_labevents_base
    UNION ALL
    -- ⑧ comments
    SELECT _pk, subject_id, hadm_id, \'\',
           'comments', NULL, NULL, _comments, 'string',
           '0', NULL, NULL, 8
    FROM q_labevents_base
    UNION ALL
    -- ⑨ order_provider_id
    SELECT _pk, subject_id, hadm_id, \'\',
           'order_provider_id', NULL, NULL, _order_provider_id, _var_type(_order_provider_id),
           '0', NULL, NULL, 9
    FROM q_labevents_base
),
-- ════════════════════════════════════════════════════════════════════
-- ④ EVENT 테이블 - chartevents (JOIN + label 방식)
--    §1.5.3: Variable_name = d_items.label (ICU 관찰 항목명)
--    §1.5.5: Event_date = charttime
--    Is_categorical: valuenum 없고 value 있으면 string → '1', 아니면 '0'
--    Mapping rule 4: Mapping_info_1='event', Mapping_info_2='chart_event'
--    원본 1행 → 1 QUIQ 행
-- ════════════════════════════════════════════════════════════════════

-- ── icu.chartevents ──────────────────────────────────────────────
q_chartevents_base AS (
    SELECT
        ROW_NUMBER() OVER (ORDER BY ce.subject_id, ce.hadm_id, ce.charttime) - 1 AS _pk,
        ce.subject_id, ce.hadm_id,
        CAST(ce.itemid AS STRING)                             AS _itemid,
        COALESCE(di.label, CAST(ce.itemid AS STRING))         AS _var_name,
        CAST(ce.charttime AS STRING)                          AS _ev,
        CAST(ce.valueuom  AS STRING)                          AS _vu,
        COALESCE(
            CASE WHEN ce.valuenum IS NOT NULL
                 THEN CAST(ce.valuenum AS STRING) END,
            CAST(ce.`value` AS STRING)
        )                                                       AS _val,
        CASE WHEN ce.valuenum IS NOT NULL THEN 'numeric'
             ELSE _var_type(CAST(ce.`value` AS STRING)) END   AS _vtype,
        CASE WHEN ce.valuenum IS NULL AND ce.`value` IS NOT NULL
             THEN '1' ELSE '0' END                             AS _iscat,
        COALESCE(CAST(ce.storetime    AS STRING), '')         AS _storetime,
        COALESCE(CAST(ce.valuenum     AS STRING), '')         AS _valuenum,
        COALESCE(CAST(ce.warning      AS STRING), '')         AS _warning,
        COALESCE(CAST(ce.stay_id      AS STRING), '')         AS _stay_id,
        COALESCE(CAST(ce.caregiver_id AS STRING), '')         AS _caregiver_id
    FROM `physionet-data`.mimiciv_3_1_icu.chartevents ce
    LEFT JOIN `physionet-data`.mimiciv_3_1_icu.d_items di ON ce.itemid = di.itemid
),
q_chartevents_all AS (
    -- ① value (메인 측정값)
    SELECT _pk, subject_id, hadm_id, _itemid,
           _var_name AS _vname, _ev, _vu, _val, _vtype,
           _iscat AS _iscat, 'event' AS _m1, 'chart_event' AS _m2, 1 AS _rtype
    FROM q_chartevents_base
    UNION ALL
    -- ② storetime
    SELECT _pk, subject_id, hadm_id, \'\',
           'storetime', NULL, NULL, _storetime, _var_type(_storetime),
           '0', 'date', NULL, 2
    FROM q_chartevents_base
    UNION ALL
    -- ③ valuenum
    SELECT _pk, subject_id, hadm_id, \'\',
           'valuenum', _ev, _vu, _valuenum, _var_type(_valuenum),
           '0', 'event', 'chart_event', 3
    FROM q_chartevents_base
    UNION ALL
    -- ④ warning
    SELECT _pk, subject_id, hadm_id, \'\',
           'warning', _ev, NULL, _warning, 'string',
           '1', NULL, NULL, 4
    FROM q_chartevents_base
    UNION ALL
    -- ⑤ stay_id
    SELECT _pk, subject_id, hadm_id, \'\',
           'stay_id', NULL, NULL, _stay_id, _var_type(_stay_id),
           '0', NULL, NULL, 5
    FROM q_chartevents_base
    UNION ALL
    -- ⑥ caregiver_id
    SELECT _pk, subject_id, hadm_id, \'\',
           'caregiver_id', NULL, NULL, _caregiver_id, _var_type(_caregiver_id),
           '0', NULL, NULL, 6
    FROM q_chartevents_base
),
-- ════════════════════════════════════════════════════════════════════
-- ① ICU WIDE 테이블 (UNPIVOT)
-- ════════════════════════════════════════════════════════════════════

-- ── icu.datetimeevents ───────────────────────────────────────────
q_datetimeevents_base AS (
    SELECT
        ROW_NUMBER() OVER (ORDER BY de.subject_id, de.hadm_id, de.charttime) - 1 AS _pk,
        de.subject_id, de.hadm_id,
        CAST(de.itemid AS STRING)                             AS _itemid,
        COALESCE(di.label, CAST(de.itemid AS STRING))         AS _var_name,
        CAST(de.charttime AS STRING)                          AS _ev,
        CAST(de.valueuom  AS STRING)                          AS _vu,
        COALESCE(CAST(de.`value`      AS STRING), '')         AS _val,
        COALESCE(CAST(de.storetime    AS STRING), '')         AS _storetime,
        COALESCE(CAST(de.warning      AS STRING), '')         AS _warning,
        COALESCE(CAST(de.stay_id      AS STRING), '')         AS _stay_id,
        COALESCE(CAST(de.caregiver_id AS STRING), '')         AS _caregiver_id
    FROM `physionet-data`.mimiciv_3_1_icu.datetimeevents de
    LEFT JOIN `physionet-data`.mimiciv_3_1_icu.d_items di ON de.itemid = di.itemid
),
q_datetimeevents_all AS (
    -- ① value (메인 측정값 - ICU charted datetime: Rule 4 chart_event)
    SELECT _pk, subject_id, hadm_id, _itemid,
           _var_name AS _vname, _ev, _vu, _val, _var_type(_val) AS _vtype,
           '0' AS _iscat, 'event' AS _m1, 'chart_event' AS _m2, 1 AS _rtype
    FROM q_datetimeevents_base
    UNION ALL
    -- ② storetime
    SELECT _pk, subject_id, hadm_id, \'\',
           'storetime', NULL, NULL, _storetime, _var_type(_storetime),
           '0', 'date', NULL, 2
    FROM q_datetimeevents_base
    UNION ALL
    -- ③ warning
    SELECT _pk, subject_id, hadm_id, \'\',
           'warning', _ev, NULL, _warning, 'string',
           '1', NULL, NULL, 3
    FROM q_datetimeevents_base
    UNION ALL
    -- ④ stay_id
    SELECT _pk, subject_id, hadm_id, \'\',
           'stay_id', NULL, NULL, _stay_id, _var_type(_stay_id),
           '0', NULL, NULL, 4
    FROM q_datetimeevents_base
    UNION ALL
    -- ⑤ caregiver_id
    SELECT _pk, subject_id, hadm_id, \'\',
           'caregiver_id', NULL, NULL, _caregiver_id, _var_type(_caregiver_id),
           '0', NULL, NULL, 5
    FROM q_datetimeevents_base
),

-- ── icu.icustays ─────────────────────────────────────────────────
t_icustays AS (
    SELECT ROW_NUMBER() OVER (ORDER BY subject_id) - 1 AS _pk,
        subject_id, hadm_id,
        COALESCE(CAST(first_careunit AS STRING), '') AS first_careunit,
        COALESCE(CAST(last_careunit  AS STRING), '') AS last_careunit,
        COALESCE(CAST(intime         AS STRING), '') AS intime,
        COALESCE(CAST(outtime        AS STRING), '') AS outtime,
        COALESCE(CAST(los            AS STRING), '') AS los
    FROM `physionet-data`.mimiciv_3_1_icu.icustays
),
u_icustays AS (
    SELECT * FROM t_icustays
    UNPIVOT (raw_val FOR Variable_name IN (first_careunit, last_careunit, intime, outtime, los))
),

-- ── icu.ingredientevents ─────────────────────────────────────────
q_ingredientevents_base AS (
    SELECT
        ROW_NUMBER() OVER (ORDER BY ie.subject_id, ie.hadm_id, ie.starttime) - 1 AS _pk,
        ie.subject_id, ie.hadm_id,
        CAST(ie.itemid AS STRING)                          AS _itemid,
        COALESCE(di.label, CAST(ie.itemid AS STRING))      AS _var_name,
        CAST(ie.starttime AS STRING)                       AS _ev,
        CAST(ie.amountuom AS STRING)                       AS _au,
        CAST(ie.rateuom   AS STRING)                       AS _ru,
        COALESCE(CAST(ie.amount            AS STRING), '') AS _val,
        COALESCE(CAST(ie.starttime         AS STRING), '') AS _starttime,
        COALESCE(CAST(ie.endtime           AS STRING), '') AS _endtime,
        COALESCE(CAST(ie.storetime         AS STRING), '') AS _storetime,
        COALESCE(CAST(ie.rate              AS STRING), '') AS _rate,
        COALESCE(CAST(ie.statusdescription AS STRING), '') AS _statusdescription,
        COALESCE(CAST(ie.originalamount    AS STRING), '') AS _originalamount,
        COALESCE(CAST(ie.originalrate      AS STRING), '') AS _originalrate,
        COALESCE(CAST(ie.stay_id           AS STRING), '') AS _stay_id,
        COALESCE(CAST(ie.caregiver_id      AS STRING), '') AS _caregiver_id,
        COALESCE(CAST(ie.orderid           AS STRING), '') AS _orderid,
        COALESCE(CAST(ie.linkorderid       AS STRING), '') AS _linkorderid
    FROM `physionet-data`.mimiciv_3_1_icu.ingredientevents ie
    LEFT JOIN `physionet-data`.mimiciv_3_1_icu.d_items di ON ie.itemid = di.itemid
),
q_ingredientevents_all AS (
    -- ① amount (메인 측정값 - I&O event: Rule 4, map2=NULL)
    SELECT _pk, subject_id, hadm_id, _itemid,
           _var_name AS _vname, _ev, _au AS _vu, _val, _var_type(_val) AS _vtype,
           '0' AS _iscat, 'event' AS _m1, CAST(NULL AS STRING) AS _m2, 1 AS _rtype
    FROM q_ingredientevents_base
    UNION ALL
    -- ② starttime
    SELECT _pk, subject_id, hadm_id, \'\',
           'starttime', NULL, NULL, _starttime, _var_type(_starttime),
           '0', 'date', NULL, 2
    FROM q_ingredientevents_base
    UNION ALL
    -- ③ endtime
    SELECT _pk, subject_id, hadm_id, \'\',
           'endtime', NULL, NULL, _endtime, _var_type(_endtime),
           '0', 'date', NULL, 3
    FROM q_ingredientevents_base
    UNION ALL
    -- ④ storetime
    SELECT _pk, subject_id, hadm_id, \'\',
           'storetime', NULL, NULL, _storetime, _var_type(_storetime),
           '0', 'date', NULL, 4
    FROM q_ingredientevents_base
    UNION ALL
    -- ⑤ rate (I&O event)
    SELECT _pk, subject_id, hadm_id, \'\',
           'rate', _ev, _ru, _rate, _var_type(_rate),
           '0', 'event', NULL, 5
    FROM q_ingredientevents_base
    UNION ALL
    -- ⑥ statusdescription
    SELECT _pk, subject_id, hadm_id, \'\',
           'statusdescription', NULL, NULL, _statusdescription, 'string',
           '1', NULL, NULL, 6
    FROM q_ingredientevents_base
    UNION ALL
    -- ⑦ originalamount
    SELECT _pk, subject_id, hadm_id, \'\',
           'originalamount', NULL, _au, _originalamount, _var_type(_originalamount),
           '0', NULL, NULL, 7
    FROM q_ingredientevents_base
    UNION ALL
    -- ⑧ originalrate
    SELECT _pk, subject_id, hadm_id, \'\',
           'originalrate', NULL, _ru, _originalrate, _var_type(_originalrate),
           '0', NULL, NULL, 8
    FROM q_ingredientevents_base
    UNION ALL
    -- ⑨ stay_id
    SELECT _pk, subject_id, hadm_id, \'\',
           'stay_id', NULL, NULL, _stay_id, _var_type(_stay_id),
           '0', NULL, NULL, 9
    FROM q_ingredientevents_base
    UNION ALL
    -- ⑩ caregiver_id
    SELECT _pk, subject_id, hadm_id, \'\',
           'caregiver_id', NULL, NULL, _caregiver_id, _var_type(_caregiver_id),
           '0', NULL, NULL, 10
    FROM q_ingredientevents_base
    UNION ALL
    -- ⑪ orderid
    SELECT _pk, subject_id, hadm_id, \'\',
           'orderid', NULL, NULL, _orderid, _var_type(_orderid),
           '0', NULL, NULL, 11
    FROM q_ingredientevents_base
    UNION ALL
    -- ⑫ linkorderid
    SELECT _pk, subject_id, hadm_id, \'\',
           'linkorderid', NULL, NULL, _linkorderid, _var_type(_linkorderid),
           '0', NULL, NULL, 12
    FROM q_ingredientevents_base
),

-- ── icu.inputevents ──────────────────────────────────────────────
q_inputevents_base AS (
    SELECT
        ROW_NUMBER() OVER (ORDER BY ie.subject_id, ie.hadm_id, ie.starttime) - 1 AS _pk,
        ie.subject_id, ie.hadm_id,
        CAST(ie.itemid AS STRING)                                  AS _itemid,
        COALESCE(di.label, CAST(ie.itemid AS STRING))              AS _var_name,
        CAST(ie.starttime      AS STRING)                          AS _ev,
        CAST(ie.amountuom      AS STRING)                          AS _au,
        CAST(ie.rateuom        AS STRING)                          AS _ru,
        CAST(ie.totalamountuom AS STRING)                          AS _tau,
        COALESCE(CAST(ie.amount                        AS STRING), '') AS _val,
        COALESCE(CAST(ie.starttime                     AS STRING), '') AS _starttime,
        COALESCE(CAST(ie.endtime                       AS STRING), '') AS _endtime,
        COALESCE(CAST(ie.storetime                     AS STRING), '') AS _storetime,
        COALESCE(CAST(ie.rate                          AS STRING), '') AS _rate,
        COALESCE(CAST(ie.ordercategoryname             AS STRING), '') AS _ordercategoryname,
        COALESCE(CAST(ie.secondaryordercategoryname    AS STRING), '') AS _secondaryordercategoryname,
        COALESCE(CAST(ie.ordercomponenttypedescription AS STRING), '') AS _ordercomponenttypedescription,
        COALESCE(CAST(ie.ordercategorydescription      AS STRING), '') AS _ordercategorydescription,
        COALESCE(CAST(ie.patientweight                 AS STRING), '') AS _patientweight,
        COALESCE(CAST(ie.totalamount                   AS STRING), '') AS _totalamount,
        COALESCE(CAST(ie.totalamountuom                AS STRING), '') AS _totalamountuom,
        COALESCE(CAST(ie.isopenbag                     AS STRING), '') AS _isopenbag,
        COALESCE(CAST(ie.continueinnextdept            AS STRING), '') AS _continueinnextdept,
        COALESCE(CAST(ie.statusdescription             AS STRING), '') AS _statusdescription,
        COALESCE(CAST(ie.originalamount                AS STRING), '') AS _originalamount,
        COALESCE(CAST(ie.originalrate                  AS STRING), '') AS _originalrate,
        COALESCE(CAST(ie.stay_id                       AS STRING), '') AS _stay_id,
        COALESCE(CAST(ie.caregiver_id                  AS STRING), '') AS _caregiver_id,
        COALESCE(CAST(ie.orderid                       AS STRING), '') AS _orderid,
        COALESCE(CAST(ie.linkorderid                   AS STRING), '') AS _linkorderid
    FROM `physionet-data`.mimiciv_3_1_icu.inputevents ie
    LEFT JOIN `physionet-data`.mimiciv_3_1_icu.d_items di ON ie.itemid = di.itemid
),
q_inputevents_all AS (
    -- ① amount (메인 측정값 - I&O event: Rule 4, map2=NULL)
    SELECT _pk, subject_id, hadm_id, _itemid,
           _var_name AS _vname, _ev, _au AS _vu, _val, _var_type(_val) AS _vtype,
           '0' AS _iscat, 'event' AS _m1, CAST(NULL AS STRING) AS _m2, 1 AS _rtype
    FROM q_inputevents_base
    UNION ALL
    -- ② starttime
    SELECT _pk, subject_id, hadm_id, \'\',
           'starttime', NULL, NULL, _starttime, _var_type(_starttime),
           '0', 'date', NULL, 2
    FROM q_inputevents_base
    UNION ALL
    -- ③ endtime
    SELECT _pk, subject_id, hadm_id, \'\',
           'endtime', NULL, NULL, _endtime, _var_type(_endtime),
           '0', 'date', NULL, 3
    FROM q_inputevents_base
    UNION ALL
    -- ④ storetime
    SELECT _pk, subject_id, hadm_id, \'\',
           'storetime', NULL, NULL, _storetime, _var_type(_storetime),
           '0', 'date', NULL, 4
    FROM q_inputevents_base
    UNION ALL
    -- ⑤ rate (I&O event)
    SELECT _pk, subject_id, hadm_id, \'\',
           'rate', _ev, _ru, _rate, _var_type(_rate),
           '0', 'event', NULL, 5
    FROM q_inputevents_base
    UNION ALL
    -- ⑥ ordercategoryname
    SELECT _pk, subject_id, hadm_id, \'\',
           'ordercategoryname', NULL, NULL, _ordercategoryname, 'string',
           '1', NULL, NULL, 6
    FROM q_inputevents_base
    UNION ALL
    -- ⑦ secondaryordercategoryname
    SELECT _pk, subject_id, hadm_id, \'\',
           'secondaryordercategoryname', NULL, NULL, _secondaryordercategoryname, 'string',
           '1', NULL, NULL, 7
    FROM q_inputevents_base
    UNION ALL
    -- ⑧ ordercomponenttypedescription
    SELECT _pk, subject_id, hadm_id, \'\',
           'ordercomponenttypedescription', NULL, NULL, _ordercomponenttypedescription, 'string',
           '1', NULL, NULL, 8
    FROM q_inputevents_base
    UNION ALL
    -- ⑨ ordercategorydescription
    SELECT _pk, subject_id, hadm_id, \'\',
           'ordercategorydescription', NULL, NULL, _ordercategorydescription, 'string',
           '1', NULL, NULL, 9
    FROM q_inputevents_base
    UNION ALL
    -- ⑩ patientweight (임상 측정값: Rule 4)
    SELECT _pk, subject_id, hadm_id, \'\',
           'patientweight', NULL, NULL, _patientweight, _var_type(_patientweight),
           '0', 'event', NULL, 10
    FROM q_inputevents_base
    UNION ALL
    -- ⑪ totalamount (I&O event)
    SELECT _pk, subject_id, hadm_id, \'\',
           'totalamount', NULL, _tau, _totalamount, _var_type(_totalamount),
           '0', 'event', NULL, 11
    FROM q_inputevents_base
    UNION ALL
    -- ⑫ totalamountuom
    SELECT _pk, subject_id, hadm_id, \'\',
           'totalamountuom', NULL, NULL, _totalamountuom, 'string',
           '0', NULL, NULL, 12
    FROM q_inputevents_base
    UNION ALL
    -- ⑬ isopenbag
    SELECT _pk, subject_id, hadm_id, \'\',
           'isopenbag', NULL, NULL, _isopenbag, _var_type(_isopenbag),
           '1', NULL, NULL, 13
    FROM q_inputevents_base
    UNION ALL
    -- ⑭ continueinnextdept
    SELECT _pk, subject_id, hadm_id, \'\',
           'continueinnextdept', NULL, NULL, _continueinnextdept, _var_type(_continueinnextdept),
           '1', NULL, NULL, 14
    FROM q_inputevents_base
    UNION ALL
    -- ⑮ statusdescription
    SELECT _pk, subject_id, hadm_id, \'\',
           'statusdescription', NULL, NULL, _statusdescription, 'string',
           '1', NULL, NULL, 15
    FROM q_inputevents_base
    UNION ALL
    -- ⑯ originalamount
    SELECT _pk, subject_id, hadm_id, \'\',
           'originalamount', NULL, _au, _originalamount, _var_type(_originalamount),
           '0', NULL, NULL, 16
    FROM q_inputevents_base
    UNION ALL
    -- ⑰ originalrate
    SELECT _pk, subject_id, hadm_id, \'\',
           'originalrate', NULL, _ru, _originalrate, _var_type(_originalrate),
           '0', NULL, NULL, 17
    FROM q_inputevents_base
    UNION ALL
    -- ⑱ stay_id
    SELECT _pk, subject_id, hadm_id, \'\',
           'stay_id', NULL, NULL, _stay_id, _var_type(_stay_id),
           '0', NULL, NULL, 18
    FROM q_inputevents_base
    UNION ALL
    -- ⑲ caregiver_id
    SELECT _pk, subject_id, hadm_id, \'\',
           'caregiver_id', NULL, NULL, _caregiver_id, _var_type(_caregiver_id),
           '0', NULL, NULL, 19
    FROM q_inputevents_base
    UNION ALL
    -- ⑳ orderid
    SELECT _pk, subject_id, hadm_id, \'\',
           'orderid', NULL, NULL, _orderid, _var_type(_orderid),
           '0', NULL, NULL, 20
    FROM q_inputevents_base
    UNION ALL
    -- ㉑ linkorderid
    SELECT _pk, subject_id, hadm_id, \'\',
           'linkorderid', NULL, NULL, _linkorderid, _var_type(_linkorderid),
           '0', NULL, NULL, 21
    FROM q_inputevents_base
),

-- ── icu.outputevents ─────────────────────────────────────────────
q_outputevents_base AS (
    SELECT
        ROW_NUMBER() OVER (ORDER BY oe.subject_id, oe.hadm_id, oe.charttime) - 1 AS _pk,
        oe.subject_id, oe.hadm_id,
        CAST(oe.itemid AS STRING)                          AS _itemid,
        COALESCE(di.label, CAST(oe.itemid AS STRING))      AS _var_name,
        CAST(oe.charttime AS STRING)                       AS _ev,
        CAST(oe.valueuom  AS STRING)                       AS _vu,
        COALESCE(CAST(oe.`value`      AS STRING), '')      AS _val,
        COALESCE(CAST(oe.storetime    AS STRING), '')      AS _storetime,
        COALESCE(CAST(oe.stay_id      AS STRING), '')      AS _stay_id,
        COALESCE(CAST(oe.caregiver_id AS STRING), '')      AS _caregiver_id
    FROM `physionet-data`.mimiciv_3_1_icu.outputevents oe
    LEFT JOIN `physionet-data`.mimiciv_3_1_icu.d_items di ON oe.itemid = di.itemid
),
q_outputevents_all AS (
    -- ① value (메인 측정값 - I&O event: Rule 4, map2=NULL)
    SELECT _pk, subject_id, hadm_id, _itemid,
           _var_name AS _vname, _ev, _vu, _val, _var_type(_val) AS _vtype,
           '0' AS _iscat, 'event' AS _m1, CAST(NULL AS STRING) AS _m2, 1 AS _rtype
    FROM q_outputevents_base
    UNION ALL
    -- ② storetime
    SELECT _pk, subject_id, hadm_id, \'\',
           'storetime', NULL, NULL, _storetime, _var_type(_storetime),
           '0', 'date', NULL, 2
    FROM q_outputevents_base
    UNION ALL
    -- ③ stay_id
    SELECT _pk, subject_id, hadm_id, \'\',
           'stay_id', NULL, NULL, _stay_id, _var_type(_stay_id),
           '0', NULL, NULL, 3
    FROM q_outputevents_base
    UNION ALL
    -- ④ caregiver_id
    SELECT _pk, subject_id, hadm_id, \'\',
           'caregiver_id', NULL, NULL, _caregiver_id, _var_type(_caregiver_id),
           '0', NULL, NULL, 4
    FROM q_outputevents_base
),

-- ── icu.procedureevents ──────────────────────────────────────────
q_procedureevents_base AS (
    SELECT
        ROW_NUMBER() OVER (ORDER BY pe.subject_id, pe.hadm_id, pe.starttime) - 1 AS _pk,
        pe.subject_id, pe.hadm_id,
        CAST(pe.itemid AS STRING)                          AS _itemid,
        COALESCE(di.label, CAST(pe.itemid AS STRING))      AS _var_name,
        CAST(pe.starttime AS STRING)                       AS _ev,
        CAST(pe.valueuom AS STRING)                        AS _vu,
        COALESCE(CAST(pe.`value`                    AS STRING), '') AS _val,
        COALESCE(CAST(pe.starttime                  AS STRING), '') AS _starttime,
        COALESCE(CAST(pe.endtime                    AS STRING), '') AS _endtime,
        COALESCE(CAST(pe.storetime                  AS STRING), '') AS _storetime,
        COALESCE(CAST(pe.`location`                 AS STRING), '') AS _location,
        COALESCE(CAST(pe.locationcategory           AS STRING), '') AS _locationcategory,
        COALESCE(CAST(pe.ordercategoryname          AS STRING), '') AS _ordercategoryname,
        COALESCE(CAST(pe.ordercategorydescription   AS STRING), '') AS _ordercategorydescription,
        COALESCE(CAST(pe.patientweight              AS STRING), '') AS _patientweight,
        COALESCE(CAST(pe.isopenbag                  AS STRING), '') AS _isopenbag,
        COALESCE(CAST(pe.continueinnextdept         AS STRING), '') AS _continueinnextdept,
        COALESCE(CAST(pe.statusdescription          AS STRING), '') AS _statusdescription,
        COALESCE(CAST(pe.stay_id                    AS STRING), '') AS _stay_id,
        COALESCE(CAST(pe.caregiver_id               AS STRING), '') AS _caregiver_id,
        COALESCE(CAST(pe.orderid                    AS STRING), '') AS _orderid,
        COALESCE(CAST(pe.linkorderid                AS STRING), '') AS _linkorderid
    FROM `physionet-data`.mimiciv_3_1_icu.procedureevents pe
    LEFT JOIN `physionet-data`.mimiciv_3_1_icu.d_items di ON pe.itemid = di.itemid
),
q_procedureevents_all AS (
    -- ① value (메인 측정값 - ICU 처치: Rule 8 procedure)
    SELECT _pk, subject_id, hadm_id, _itemid,
           _var_name AS _vname, _ev, _vu, _val, _var_type(_val) AS _vtype,
           '0' AS _iscat, 'procedure' AS _m1, CAST(NULL AS STRING) AS _m2, 1 AS _rtype
    FROM q_procedureevents_base
    UNION ALL
    -- ② starttime
    SELECT _pk, subject_id, hadm_id, \'\',
           'starttime', NULL, NULL, _starttime, _var_type(_starttime),
           '0', 'date', NULL, 2
    FROM q_procedureevents_base
    UNION ALL
    -- ③ endtime
    SELECT _pk, subject_id, hadm_id, \'\',
           'endtime', NULL, NULL, _endtime, _var_type(_endtime),
           '0', 'date', NULL, 3
    FROM q_procedureevents_base
    UNION ALL
    -- ④ storetime
    SELECT _pk, subject_id, hadm_id, \'\',
           'storetime', NULL, NULL, _storetime, _var_type(_storetime),
           '0', 'date', NULL, 4
    FROM q_procedureevents_base
    UNION ALL
    -- ⑤ location
    SELECT _pk, subject_id, hadm_id, \'\',
           'location', _ev, NULL, _location, 'string',
           '1', NULL, NULL, 5
    FROM q_procedureevents_base
    UNION ALL
    -- ⑥ locationcategory
    SELECT _pk, subject_id, hadm_id, \'\',
           'locationcategory', _ev, NULL, _locationcategory, 'string',
           '1', NULL, NULL, 6
    FROM q_procedureevents_base
    UNION ALL
    -- ⑦ ordercategoryname
    SELECT _pk, subject_id, hadm_id, \'\',
           'ordercategoryname', NULL, NULL, _ordercategoryname, 'string',
           '1', NULL, NULL, 7
    FROM q_procedureevents_base
    UNION ALL
    -- ⑧ ordercategorydescription
    SELECT _pk, subject_id, hadm_id, \'\',
           'ordercategorydescription', NULL, NULL, _ordercategorydescription, 'string',
           '1', NULL, NULL, 8
    FROM q_procedureevents_base
    UNION ALL
    -- ⑨ patientweight (임상 측정값: Rule 4)
    SELECT _pk, subject_id, hadm_id, \'\',
           'patientweight', NULL, NULL, _patientweight, _var_type(_patientweight),
           '0', 'event', NULL, 9
    FROM q_procedureevents_base
    UNION ALL
    -- ⑩ isopenbag
    SELECT _pk, subject_id, hadm_id, \'\',
           'isopenbag', NULL, NULL, _isopenbag, _var_type(_isopenbag),
           '1', NULL, NULL, 10
    FROM q_procedureevents_base
    UNION ALL
    -- ⑪ continueinnextdept
    SELECT _pk, subject_id, hadm_id, \'\',
           'continueinnextdept', NULL, NULL, _continueinnextdept, _var_type(_continueinnextdept),
           '1', NULL, NULL, 11
    FROM q_procedureevents_base
    UNION ALL
    -- ⑫ statusdescription
    SELECT _pk, subject_id, hadm_id, \'\',
           'statusdescription', NULL, NULL, _statusdescription, 'string',
           '1', NULL, NULL, 12
    FROM q_procedureevents_base
    UNION ALL
    -- ⑬ stay_id
    SELECT _pk, subject_id, hadm_id, \'\',
           'stay_id', NULL, NULL, _stay_id, _var_type(_stay_id),
           '0', NULL, NULL, 13
    FROM q_procedureevents_base
    UNION ALL
    -- ⑭ caregiver_id
    SELECT _pk, subject_id, hadm_id, \'\',
           'caregiver_id', NULL, NULL, _caregiver_id, _var_type(_caregiver_id),
           '0', NULL, NULL, 14
    FROM q_procedureevents_base
    UNION ALL
    -- ⑮ orderid
    SELECT _pk, subject_id, hadm_id, \'\',
           'orderid', NULL, NULL, _orderid, _var_type(_orderid),
           '0', NULL, NULL, 15
    FROM q_procedureevents_base
    UNION ALL
    -- ⑯ linkorderid
    SELECT _pk, subject_id, hadm_id, \'\',
           'linkorderid', NULL, NULL, _linkorderid, _var_type(_linkorderid),
           '0', NULL, NULL, 16
    FROM q_procedureevents_base
),
-- ════════════════════════════════════════════════════════════════════
-- ① ED WIDE 테이블 (UNPIVOT)
-- ════════════════════════════════════════════════════════════════════

-- ── ed.diagnosis ─────────────────────────────────────────────────
t_diagnosis AS (
    SELECT ROW_NUMBER() OVER (ORDER BY subject_id) - 1 AS _pk,
        subject_id,
        COALESCE(CAST(seq_num      AS STRING), '') AS seq_num,
        COALESCE(CAST(icd_code     AS STRING), '') AS icd_code,
        COALESCE(CAST(icd_version  AS STRING), '') AS icd_version,
        COALESCE(CAST(icd_title    AS STRING), '') AS icd_title
    FROM `physionet-data`.mimiciv_ed.diagnosis
),
u_diagnosis AS (
    SELECT * FROM t_diagnosis
    UNPIVOT (raw_val FOR Variable_name IN (seq_num, icd_code, icd_version, icd_title))
),

-- ── ed.edstays ───────────────────────────────────────────────────
t_edstays AS (
    SELECT ROW_NUMBER() OVER (ORDER BY subject_id) - 1 AS _pk,
        subject_id, hadm_id,
        COALESCE(CAST(intime            AS STRING), '') AS intime,
        COALESCE(CAST(outtime           AS STRING), '') AS outtime,
        COALESCE(CAST(gender            AS STRING), '') AS gender,
        COALESCE(CAST(race              AS STRING), '') AS race,
        COALESCE(CAST(arrival_transport AS STRING), '') AS arrival_transport,
        COALESCE(CAST(disposition       AS STRING), '') AS disposition
    FROM `physionet-data`.mimiciv_ed.edstays
),
u_edstays AS (
    SELECT * FROM t_edstays
    UNPIVOT (raw_val FOR Variable_name IN (intime, outtime, gender, race, arrival_transport, disposition))
),

-- ── ed.medrecon ──────────────────────────────────────────────────
t_medrecon AS (
    SELECT ROW_NUMBER() OVER (ORDER BY subject_id) - 1 AS _pk,
        subject_id,
        CAST(charttime AS STRING)                       AS _ev,
        COALESCE(CAST(`name`       AS STRING), '') AS `name`,
        COALESCE(CAST(gsn          AS STRING), '') AS gsn,
        COALESCE(CAST(ndc          AS STRING), '') AS ndc,
        COALESCE(CAST(etc_rn       AS STRING), '') AS etc_rn,
        COALESCE(CAST(etccode      AS STRING), '') AS etccode,
        COALESCE(CAST(etcdescription AS STRING), '') AS etcdescription
    FROM `physionet-data`.mimiciv_ed.medrecon
),
u_medrecon AS (
    SELECT * FROM t_medrecon
    UNPIVOT (raw_val FOR Variable_name IN (`name`, gsn, ndc, etc_rn, etccode, etcdescription))
),

-- ── ed.pyxis ─────────────────────────────────────────────────────
t_pyxis AS (
    SELECT ROW_NUMBER() OVER (ORDER BY subject_id) - 1 AS _pk,
        subject_id,
        CAST(charttime AS STRING)               AS _ev,
        COALESCE(CAST(med_rn     AS STRING), '') AS med_rn,
        COALESCE(CAST(`name`     AS STRING), '') AS `name`,
        COALESCE(CAST(gsn_rn     AS STRING), '') AS gsn_rn,
        COALESCE(CAST(gsn        AS STRING), '') AS gsn
    FROM `physionet-data`.mimiciv_ed.pyxis
),
u_pyxis AS (
    SELECT * FROM t_pyxis
    UNPIVOT (raw_val FOR Variable_name IN (med_rn, `name`, gsn_rn, gsn))
),

-- ── ed.triage ────────────────────────────────────────────────────
t_triage AS (
    SELECT ROW_NUMBER() OVER (ORDER BY subject_id) - 1 AS _pk,
        subject_id,
        COALESCE(CAST(temperature    AS STRING), '') AS temperature,
        COALESCE(CAST(heartrate      AS STRING), '') AS heartrate,
        COALESCE(CAST(resprate       AS STRING), '') AS resprate,
        COALESCE(CAST(o2sat          AS STRING), '') AS o2sat,
        COALESCE(CAST(sbp            AS STRING), '') AS sbp,
        COALESCE(CAST(dbp            AS STRING), '') AS dbp,
        COALESCE(CAST(pain           AS STRING), '') AS pain,
        COALESCE(CAST(acuity         AS STRING), '') AS acuity,
        COALESCE(CAST(chiefcomplaint AS STRING), '') AS chiefcomplaint
    FROM `physionet-data`.mimiciv_ed.triage
),
u_triage AS (
    SELECT * FROM t_triage
    UNPIVOT (raw_val FOR Variable_name IN (temperature, heartrate, resprate, o2sat, sbp, dbp, pain, acuity, chiefcomplaint))
),

-- ── ed.vitalsign ─────────────────────────────────────────────────
t_vitalsign AS (
    SELECT ROW_NUMBER() OVER (ORDER BY subject_id) - 1 AS _pk,
        subject_id,
        CAST(charttime AS STRING)               AS _ev,
        COALESCE(CAST(temperature AS STRING), '') AS temperature,
        COALESCE(CAST(heartrate   AS STRING), '') AS heartrate,
        COALESCE(CAST(resprate    AS STRING), '') AS resprate,
        COALESCE(CAST(o2sat       AS STRING), '') AS o2sat,
        COALESCE(CAST(sbp         AS STRING), '') AS sbp,
        COALESCE(CAST(dbp         AS STRING), '') AS dbp,
        COALESCE(CAST(rhythm      AS STRING), '') AS rhythm,
        COALESCE(CAST(pain        AS STRING), '') AS pain
    FROM `physionet-data`.mimiciv_ed.vitalsign
),
u_vitalsign AS (
    SELECT * FROM t_vitalsign
    UNPIVOT (raw_val FOR Variable_name IN (temperature, heartrate, resprate, o2sat, sbp, dbp, rhythm, pain))
)
-- ═══════════════════════════════════════════════════════════════════
-- UNION ALL: 모든 테이블 결합
-- 컬럼 순서: Primary_key, Variable_ID, Original_table_name, Variable_name,
--            Event_date, Value, Unit, Variable_type, Is_categorical,
--            Recorder, Recorder_position, Recorder_affiliation,
--            Patient_id, Admission_id, Ground_truth,
--            Mapping_info_1, Mapping_info_2
-- ═══════════════════════════════════════════════════════════════════

-- ── ① Wide 테이블 ─────────────────────────────────────────────────
SELECT _pk AS Primary_key, '' AS Variable_ID, 'ADMISSIONS' AS Original_table_name,
       Variable_name, NULL AS Event_date, raw_val AS Value, NULL AS Unit,
       _var_type(raw_val) AS Variable_type, _is_cat(Variable_name) AS Is_categorical,
       '' AS Recorder, '' AS Recorder_position, '' AS Recorder_affiliation,
       CAST(subject_id AS STRING) AS Patient_id, CAST(hadm_id AS STRING) AS Admission_id,
       '' AS Ground_truth,
       -- Rule 5: 날짜 컬럼; Rule 4: 입원 특성 변수 → event/chart_event
       CASE Variable_name
           WHEN 'admittime'            THEN 'date'
           WHEN 'dischtime'            THEN 'date'
           WHEN 'deathtime'            THEN 'date'
           WHEN 'edregtime'            THEN 'date'
           WHEN 'edouttime'            THEN 'date'
           WHEN 'admission_type'       THEN 'event'
           WHEN 'admission_location'   THEN 'event'
           WHEN 'discharge_location'   THEN 'event'
           WHEN 'insurance'            THEN 'event'
           WHEN 'language'             THEN 'event'
           WHEN 'marital_status'       THEN 'event'
           WHEN 'race'                 THEN 'event'
           WHEN 'hospital_expire_flag' THEN 'event'
           ELSE NULL END AS Mapping_info_1,
       CASE Variable_name
           WHEN 'admission_type'       THEN 'chart_event'
           WHEN 'admission_location'   THEN 'chart_event'
           WHEN 'discharge_location'   THEN 'chart_event'
           WHEN 'insurance'            THEN 'chart_event'
           WHEN 'language'             THEN 'chart_event'
           WHEN 'marital_status'       THEN 'chart_event'
           WHEN 'race'                 THEN 'chart_event'
           WHEN 'hospital_expire_flag' THEN 'chart_event'
           ELSE NULL END AS Mapping_info_2
FROM u_admissions WHERE raw_val IS NOT NULL
UNION ALL
SELECT _pk, '', 'PATIENTS', Variable_name, NULL, raw_val, NULL,
       _var_type(raw_val), _is_cat(Variable_name), '', '', '',
       CAST(subject_id AS STRING), '', '',
       -- Rule 5: dod(사망일)
       CASE Variable_name WHEN 'dod' THEN 'date' ELSE NULL END AS Mapping_info_1,
       NULL AS Mapping_info_2
FROM u_patients WHERE raw_val IS NOT NULL
UNION ALL
SELECT _pk, '', 'TRANSFERS', Variable_name, NULL, raw_val, NULL,
       _var_type(raw_val), _is_cat(Variable_name), '', '', '',
       CAST(subject_id AS STRING), CAST(hadm_id AS STRING), '',
       -- Rule 5: 날짜 컬럼
       CASE Variable_name
           WHEN 'intime'  THEN 'date'
           WHEN 'outtime' THEN 'date'
           ELSE NULL END AS Mapping_info_1,
       NULL AS Mapping_info_2
FROM u_transfers WHERE raw_val IS NOT NULL
UNION ALL
SELECT _pk, '', 'OMR', Variable_name,
       CASE WHEN Variable_name IN ('result_name', 'result_value') THEN _ev ELSE NULL END,
       raw_val, NULL, _var_type(raw_val), _is_cat(Variable_name), '', '', '',
       CAST(subject_id AS STRING), '', '',
       -- Rule 4: result_value → 임상 관찰값(chart_event)
       CASE Variable_name WHEN 'result_value' THEN 'event' ELSE NULL END AS Mapping_info_1,
       CASE Variable_name WHEN 'result_value' THEN 'chart_event' ELSE NULL END AS Mapping_info_2
FROM u_omr WHERE raw_val IS NOT NULL
UNION ALL
SELECT _pk, '', 'DRGCODES', Variable_name, NULL, raw_val, NULL,
       _var_type(raw_val), _is_cat(Variable_name), '', '', '',
       CAST(subject_id AS STRING), CAST(hadm_id AS STRING), '',
       -- Rule 3: drg_code → medical_code
       CASE Variable_name WHEN 'drg_code' THEN 'medical_code' ELSE NULL END AS Mapping_info_1,
       NULL AS Mapping_info_2
FROM u_drgcodes WHERE raw_val IS NOT NULL
UNION ALL
SELECT _pk, '', 'EMAR', Variable_name,
       CASE WHEN Variable_name = 'medication' THEN _ev ELSE NULL END,
       raw_val, NULL, _var_type(raw_val), _is_cat(Variable_name), '', '', '',
       CAST(subject_id AS STRING), CAST(hadm_id AS STRING), '',
       -- Rule 7: medication → prescription/drug; Rule 5: 날짜 컬럼
       CASE Variable_name
           WHEN 'medication'    THEN 'prescription'
           WHEN 'scheduletime'  THEN 'date'
           WHEN 'storetime'     THEN 'date'
           ELSE NULL END AS Mapping_info_1,
       CASE Variable_name WHEN 'medication' THEN 'drug' ELSE NULL END AS Mapping_info_2
FROM u_emar WHERE raw_val IS NOT NULL
UNION ALL
SELECT _pk, '', 'EMAR_DETAIL', Variable_name, NULL, raw_val,
       CASE Variable_name
           WHEN 'dose_due'             THEN _du
           WHEN 'dose_given'           THEN _dgu
           WHEN 'product_amount_given' THEN _pu
           WHEN 'infusion_rate'        THEN _iru
           ELSE NULL END,
       _var_type(raw_val), _is_cat(Variable_name), '', '', '',
       CAST(subject_id AS STRING), '', '',
       -- Rule 7: 약물명/투여 정보; Rule 3: product_code → medical_code
       CASE Variable_name
           WHEN 'product_description' THEN 'prescription'
           WHEN 'product_code'        THEN 'medical_code'
           WHEN 'dose_due'            THEN 'prescription'
           WHEN 'dose_given'          THEN 'prescription'
           WHEN 'infusion_rate'       THEN 'prescription'
           WHEN 'route'               THEN 'prescription'
           ELSE NULL END AS Mapping_info_1,
       CASE Variable_name
           WHEN 'product_description' THEN 'drug'
           WHEN 'dose_due'            THEN 'prescription_info'
           WHEN 'dose_given'          THEN 'prescription_info'
           WHEN 'infusion_rate'       THEN 'prescription_info'
           WHEN 'route'               THEN 'prescription_info'
           ELSE NULL END AS Mapping_info_2
FROM u_emar_detail WHERE raw_val IS NOT NULL
UNION ALL
SELECT _pk, '', 'HCPCSEVENTS', Variable_name,
       CASE WHEN Variable_name = 'hcpcs_cd' THEN _ev ELSE NULL END,
       raw_val, NULL, _var_type(raw_val), _is_cat(Variable_name), '', '', '',
       CAST(subject_id AS STRING), CAST(hadm_id AS STRING), '',
       -- Rule 3: hcpcs_cd → medical_code; Rule 8: short_description → procedure
       CASE Variable_name
           WHEN 'hcpcs_cd'          THEN 'medical_code'
           WHEN 'short_description' THEN 'procedure'
           ELSE NULL END AS Mapping_info_1,
       NULL AS Mapping_info_2
FROM u_hcpcsevents WHERE raw_val IS NOT NULL
UNION ALL
SELECT _pk, '', 'MICROBIOLOGYEVENTS', Variable_name,
       CASE WHEN Variable_name IN (
           'spec_type_desc', 'test_name', 'org_name', 'isolate_num', 'quantity',
           'ab_name', 'dilution_text', 'dilution_comparison', 'dilution_value', 'interpretation'
       ) THEN _ev ELSE NULL END,
       raw_val, NULL, _var_type(raw_val), _is_cat(Variable_name), '', '', '',
       CAST(subject_id AS STRING), CAST(hadm_id AS STRING), '',
       -- Rule 4: 미생물 검사 결과값 → event/lab_event; Rule 5: 날짜
       CASE Variable_name
           WHEN 'storedate'           THEN 'date'
           WHEN 'storetime'           THEN 'date'
           WHEN 'test_name'           THEN 'event'
           WHEN 'org_name'            THEN 'event'
           WHEN 'quantity'            THEN 'event'
           WHEN 'ab_name'             THEN 'event'
           WHEN 'dilution_text'       THEN 'event'
           WHEN 'dilution_comparison' THEN 'event'
           WHEN 'dilution_value'      THEN 'event'
           WHEN 'interpretation'      THEN 'event'
           ELSE NULL END AS Mapping_info_1,
       CASE Variable_name
           WHEN 'test_name'           THEN 'lab_event'
           WHEN 'org_name'            THEN 'lab_event'
           WHEN 'quantity'            THEN 'lab_event'
           WHEN 'ab_name'             THEN 'lab_event'
           WHEN 'dilution_text'       THEN 'lab_event'
           WHEN 'dilution_comparison' THEN 'lab_event'
           WHEN 'dilution_value'      THEN 'lab_event'
           WHEN 'interpretation'      THEN 'lab_event'
           ELSE NULL END AS Mapping_info_2
FROM u_micro WHERE raw_val IS NOT NULL
UNION ALL
SELECT _pk, '', 'PHARMACY', Variable_name,
       CASE
           WHEN Variable_name IN ('medication', 'proc_type', 'status') THEN _ev
           WHEN Variable_name = 'expiration_value'                         THEN _expdate
           ELSE NULL END,
       raw_val,
       CASE Variable_name
           WHEN 'duration'         THEN _dur_int
           WHEN 'expiration_value' THEN _exp_unit
           ELSE NULL END,
       _var_type(raw_val), _is_cat(Variable_name), '', '', '',
       CAST(subject_id AS STRING), CAST(hadm_id AS STRING), '',
       -- Rule 5: 날짜; Rule 7: 약물명/투여정보
       CASE Variable_name
           WHEN 'starttime'        THEN 'date'
           WHEN 'stoptime'         THEN 'date'
           WHEN 'entertime'        THEN 'date'
           WHEN 'verifiedtime'     THEN 'date'
           WHEN 'expirationdate'   THEN 'date'
           WHEN 'medication'       THEN 'prescription'
           WHEN 'route'            THEN 'prescription'
           WHEN 'frequency'        THEN 'prescription'
           WHEN 'basal_rate'       THEN 'prescription'
           WHEN 'one_hr_max'       THEN 'prescription'
           WHEN 'doses_per_24_hrs' THEN 'prescription'
           WHEN 'duration'         THEN 'prescription'
           WHEN 'fill_quantity'    THEN 'prescription'
           ELSE NULL END AS Mapping_info_1,
       CASE Variable_name
           WHEN 'medication'       THEN 'drug'
           WHEN 'route'            THEN 'prescription_info'
           WHEN 'frequency'        THEN 'prescription_info'
           WHEN 'basal_rate'       THEN 'prescription_info'
           WHEN 'one_hr_max'       THEN 'prescription_info'
           WHEN 'doses_per_24_hrs' THEN 'prescription_info'
           WHEN 'duration'         THEN 'prescription_info'
           WHEN 'fill_quantity'    THEN 'prescription_info'
           ELSE NULL END AS Mapping_info_2
FROM u_pharmacy WHERE raw_val IS NOT NULL
UNION ALL
SELECT _pk, '', 'POE', Variable_name,
       CASE WHEN Variable_name IN ('order_type', 'order_subtype', 'transaction_type', 'order_status')
            THEN _ev ELSE NULL END,
       raw_val, NULL, _var_type(raw_val), _is_cat(Variable_name), '', '', '',
       CAST(subject_id AS STRING), CAST(hadm_id AS STRING), '',
       -- POE: 주문 분류 정보만 포함, 해당 Rule 없음
       NULL AS Mapping_info_1,
       NULL AS Mapping_info_2
FROM u_poe WHERE raw_val IS NOT NULL
UNION ALL
SELECT _pk, '', 'POE_DETAIL', Variable_name, NULL, raw_val, NULL,
       _var_type(raw_val), _is_cat(Variable_name), '', '', '',
       CAST(subject_id AS STRING), '', '',
       NULL AS Mapping_info_1,
       NULL AS Mapping_info_2
FROM u_poe_detail WHERE raw_val IS NOT NULL
UNION ALL
SELECT _pk, '', 'PRESCRIPTIONS', Variable_name,
       CASE WHEN Variable_name IN ('drug_type', 'drug', 'formulary_drug_cd', 'gsn', 'ndc')
            THEN _ev ELSE NULL END,
       raw_val,
       CASE Variable_name
           WHEN 'dose_val_rx'   THEN _duru
           WHEN 'form_val_disp' THEN _fudu
           ELSE NULL END,
       _var_type(raw_val), _is_cat(Variable_name), '', '', '',
       CAST(subject_id AS STRING), CAST(hadm_id AS STRING), '',
       -- Rule 5: 날짜; Rule 3: 코드; Rule 7: 약물명/투여정보
       CASE Variable_name
           WHEN 'starttime'         THEN 'date'
           WHEN 'stoptime'          THEN 'date'
           WHEN 'drug'              THEN 'prescription'
           WHEN 'formulary_drug_cd' THEN 'medical_code'
           WHEN 'gsn'               THEN 'medical_code'
           WHEN 'ndc'               THEN 'medical_code'
           WHEN 'prod_strength'     THEN 'prescription'
           WHEN 'form_rx'           THEN 'prescription'
           WHEN 'dose_val_rx'       THEN 'prescription'
           WHEN 'form_val_disp'     THEN 'prescription'
           WHEN 'doses_per_24_hrs'  THEN 'prescription'
           WHEN 'route'             THEN 'prescription'
           ELSE NULL END AS Mapping_info_1,
       CASE Variable_name
           WHEN 'drug'              THEN 'drug'
           WHEN 'prod_strength'     THEN 'prescription_info'
           WHEN 'form_rx'           THEN 'prescription_info'
           WHEN 'dose_val_rx'       THEN 'prescription_info'
           WHEN 'form_val_disp'     THEN 'prescription_info'
           WHEN 'doses_per_24_hrs'  THEN 'prescription_info'
           WHEN 'route'             THEN 'prescription_info'
           ELSE NULL END AS Mapping_info_2
FROM u_prescriptions WHERE raw_val IS NOT NULL
UNION ALL
SELECT _pk, '', 'SERVICES', Variable_name, NULL, raw_val, NULL,
       _var_type(raw_val), _is_cat(Variable_name), '', '', '',
       CAST(subject_id AS STRING), CAST(hadm_id AS STRING), '',
       -- Rule 5: transfertime → date
       CASE Variable_name WHEN 'transfertime' THEN 'date' ELSE NULL END AS Mapping_info_1,
       NULL AS Mapping_info_2
FROM u_services WHERE raw_val IS NOT NULL

-- ── ② Code 테이블 ─────────────────────────────────────────────────
UNION ALL
SELECT _pk, '', 'DIAGNOSES_ICD', Variable_name, NULL, raw_val, NULL,
       _var_type(raw_val), _is_cat(Variable_name), '', '', '',
       CAST(subject_id AS STRING), CAST(hadm_id AS STRING), '',
       -- Rule 3: icd_code → medical_code
       CASE Variable_name WHEN 'icd_code' THEN 'medical_code' ELSE NULL END AS Mapping_info_1,
       NULL AS Mapping_info_2
FROM u_diagnoses_icd
UNION ALL
SELECT _pk, '', 'PROCEDURES_ICD', Variable_name,
       CASE WHEN Variable_name = 'icd_code' THEN _ev ELSE NULL END,
       raw_val, NULL, _var_type(raw_val), _is_cat(Variable_name), '', '', '',
       CAST(subject_id AS STRING), CAST(hadm_id AS STRING), '',
       -- Rule 3: icd_code → medical_code
       CASE Variable_name WHEN 'icd_code' THEN 'medical_code' ELSE NULL END AS Mapping_info_1,
       NULL AS Mapping_info_2
FROM u_procedures_icd

-- ── ③④ Event 테이블 ───────────────────────────────────────────────
UNION ALL
SELECT _pk, _itemid, 'LABEVENTS', _vname, _ev, _val, _vu, _vtype, _iscat,
       '', '', '',
       CAST(subject_id AS STRING), CAST(hadm_id AS STRING), '',
       _m1, _m2
FROM q_labevents_all
UNION ALL
SELECT _pk, _itemid, 'CHARTEVENTS', _vname, _ev, _val, _vu, _vtype, _iscat,
       '', '', '',
       CAST(subject_id AS STRING), CAST(hadm_id AS STRING), '',
       _m1, _m2
FROM q_chartevents_all

-- ── ① ICU Wide 테이블 ─────────────────────────────────────────────
UNION ALL
SELECT _pk, _itemid, 'DATETIMEEVENTS', _vname, _ev, _val, _vu, _vtype, _iscat,
       '', '', '',
       CAST(subject_id AS STRING), CAST(hadm_id AS STRING), '',
       _m1, _m2
FROM q_datetimeevents_all
UNION ALL
SELECT _pk, '', 'ICUSTAYS', Variable_name, NULL, raw_val, NULL,
       _var_type(raw_val), _is_cat(Variable_name), '', '', '',
       CAST(subject_id AS STRING), CAST(hadm_id AS STRING), '',
       -- Rule 5: 날짜 컬럼
       CASE Variable_name
           WHEN 'intime'  THEN 'date'
           WHEN 'outtime' THEN 'date'
           ELSE NULL END AS Mapping_info_1,
       NULL AS Mapping_info_2
FROM u_icustays WHERE raw_val IS NOT NULL
UNION ALL
SELECT _pk, _itemid, 'INGREDIENTEVENTS', _vname, _ev, _val, _vu, _vtype, _iscat,
       '', '', '',
       CAST(subject_id AS STRING), CAST(hadm_id AS STRING), '',
       _m1, _m2
FROM q_ingredientevents_all
UNION ALL
SELECT _pk, _itemid, 'INPUTEVENTS', _vname, _ev, _val, _vu, _vtype, _iscat,
       '', '', '',
       CAST(subject_id AS STRING), CAST(hadm_id AS STRING), '',
       _m1, _m2
FROM q_inputevents_all
UNION ALL
SELECT _pk, _itemid, 'OUTPUTEVENTS', _vname, _ev, _val, _vu, _vtype, _iscat,
       '', '', '',
       CAST(subject_id AS STRING), CAST(hadm_id AS STRING), '',
       _m1, _m2
FROM q_outputevents_all
UNION ALL
SELECT _pk, _itemid, 'PROCEDUREEVENTS', _vname, _ev, _val, _vu, _vtype, _iscat,
       '', '', '',
       CAST(subject_id AS STRING), CAST(hadm_id AS STRING), '',
       _m1, _m2
FROM q_procedureevents_all

-- ── ① ED Wide 테이블 ──────────────────────────────────────────────
UNION ALL
SELECT _pk, '', 'DIAGNOSIS', Variable_name, NULL, raw_val, NULL,
       _var_type(raw_val), _is_cat(Variable_name), '', '', '',
       CAST(subject_id AS STRING), '', '',
       -- Rule 3: icd_code → medical_code; Rule 6: icd_title → diagnosis
       CASE Variable_name
           WHEN 'icd_code'  THEN 'medical_code'
           WHEN 'icd_title' THEN 'diagnosis'
           ELSE NULL END AS Mapping_info_1,
       NULL AS Mapping_info_2
FROM u_diagnosis WHERE raw_val IS NOT NULL
UNION ALL
SELECT _pk, '', 'EDSTAYS', Variable_name, NULL, raw_val, NULL,
       _var_type(raw_val), _is_cat(Variable_name), '', '', '',
       CAST(subject_id AS STRING), CAST(hadm_id AS STRING), '',
       -- Rule 5: 날짜 컬럼
       CASE Variable_name
           WHEN 'intime'  THEN 'date'
           WHEN 'outtime' THEN 'date'
           ELSE NULL END AS Mapping_info_1,
       NULL AS Mapping_info_2
FROM u_edstays WHERE raw_val IS NOT NULL
UNION ALL
SELECT _pk, '', 'MEDRECON', Variable_name,
       CASE WHEN Variable_name IN ('name', 'gsn', 'ndc') THEN _ev ELSE NULL END,
       raw_val, NULL, _var_type(raw_val), _is_cat(Variable_name), '', '', '',
       CAST(subject_id AS STRING), '', '',
       -- Rule 7: name → prescription/drug; Rule 3: gsn/ndc/etccode → medical_code
       CASE Variable_name
           WHEN 'name'    THEN 'prescription'
           WHEN 'gsn'     THEN 'medical_code'
           WHEN 'ndc'     THEN 'medical_code'
           WHEN 'etccode' THEN 'medical_code'
           ELSE NULL END AS Mapping_info_1,
       CASE Variable_name WHEN 'name' THEN 'drug' ELSE NULL END AS Mapping_info_2
FROM u_medrecon
UNION ALL
SELECT _pk, '', 'PYXIS', Variable_name,
       CASE WHEN Variable_name IN ('med_rn', 'name', 'gsn') THEN _ev ELSE NULL END,
       raw_val, NULL, _var_type(raw_val), _is_cat(Variable_name), '', '', '',
       CAST(subject_id AS STRING), '', '',
       -- Rule 7: name → prescription/drug; Rule 3: gsn → medical_code
       CASE Variable_name
           WHEN 'name' THEN 'prescription'
           WHEN 'gsn'  THEN 'medical_code'
           ELSE NULL END AS Mapping_info_1,
       CASE Variable_name WHEN 'name' THEN 'drug' ELSE NULL END AS Mapping_info_2
FROM u_pyxis
UNION ALL
SELECT _pk, '', 'TRIAGE', Variable_name, NULL, raw_val, NULL,
       _var_type(raw_val), _is_cat(Variable_name), '', '', '',
       CAST(subject_id AS STRING), '', '',
       -- Rule 4: 활력징후 → event/chart_event; Rule 6: chiefcomplaint → diagnosis
       CASE Variable_name
           WHEN 'temperature'    THEN 'event'
           WHEN 'heartrate'      THEN 'event'
           WHEN 'resprate'       THEN 'event'
           WHEN 'o2sat'          THEN 'event'
           WHEN 'sbp'            THEN 'event'
           WHEN 'dbp'            THEN 'event'
           WHEN 'pain'           THEN 'event'
           WHEN 'chiefcomplaint' THEN 'diagnosis'
           ELSE NULL END AS Mapping_info_1,
       CASE Variable_name
           WHEN 'temperature' THEN 'chart_event'
           WHEN 'heartrate'   THEN 'chart_event'
           WHEN 'resprate'    THEN 'chart_event'
           WHEN 'o2sat'       THEN 'chart_event'
           WHEN 'sbp'         THEN 'chart_event'
           WHEN 'dbp'         THEN 'chart_event'
           WHEN 'pain'        THEN 'chart_event'
           ELSE NULL END AS Mapping_info_2
FROM u_triage WHERE raw_val IS NOT NULL
UNION ALL
SELECT _pk, '', 'VITALSIGN', Variable_name, _ev, raw_val, NULL,
       _var_type(raw_val), _is_cat(Variable_name), '', '', '',
       CAST(subject_id AS STRING), '', '',
       -- Rule 4: 활력징후 모두 → event/chart_event
       CASE Variable_name
           WHEN 'temperature' THEN 'event'
           WHEN 'heartrate'   THEN 'event'
           WHEN 'resprate'    THEN 'event'
           WHEN 'o2sat'       THEN 'event'
           WHEN 'sbp'         THEN 'event'
           WHEN 'dbp'         THEN 'event'
           WHEN 'rhythm'      THEN 'event'
           WHEN 'pain'        THEN 'event'
           ELSE NULL END AS Mapping_info_1,
       CASE Variable_name
           WHEN 'temperature' THEN 'chart_event'
           WHEN 'heartrate'   THEN 'chart_event'
           WHEN 'resprate'    THEN 'chart_event'
           WHEN 'o2sat'       THEN 'chart_event'
           WHEN 'sbp'         THEN 'chart_event'
           WHEN 'dbp'         THEN 'chart_event'
           WHEN 'rhythm'      THEN 'chart_event'
           WHEN 'pain'        THEN 'chart_event'
           ELSE NULL END AS Mapping_info_2
FROM u_vitalsign
;