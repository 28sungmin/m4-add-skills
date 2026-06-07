from google.cloud import bigquery
import pandas as pd
import os

client = bigquery.Client(project='cmi-lab-492906')

sql = """
WITH er_admissions AS (
    SELECT subject_id, hadm_id, admittime, dischtime, admission_type,
           discharge_location, hospital_expire_flag,
           ROUND(TIMESTAMP_DIFF(dischtime, admittime, MINUTE) / 1440.0, 1) AS los_days
    FROM `cmi-lab`.mimiciv_3_1_hosp.admissions
    WHERE admission_location = 'EMERGENCY ROOM'
),
pneumonia_hadm AS (
    SELECT DISTINCT hadm_id
    FROM `cmi-lab`.mimiciv_3_1_hosp.diagnoses_icd
    WHERE
        (icd_version = 9  AND (icd_code LIKE '480%' OR icd_code LIKE '481%'
                            OR icd_code LIKE '482%' OR icd_code LIKE '483%'
                            OR icd_code LIKE '484%' OR icd_code LIKE '485%'
                            OR icd_code LIKE '486%'))
        OR
        (icd_version = 10 AND (icd_code LIKE 'J12%' OR icd_code LIKE 'J13%'
                            OR icd_code LIKE 'J14%' OR icd_code LIKE 'J15%'
                            OR icd_code LIKE 'J16%' OR icd_code LIKE 'J17%'
                            OR icd_code LIKE 'J18%'))
),
pneumonia_codes_agg AS (
    SELECT hadm_id,
           STRING_AGG(CONCAT(icd_code, '(ICD-', CAST(icd_version AS STRING), ')'),
                      ', ' ORDER BY seq_num) AS pneumonia_icd_codes
    FROM `cmi-lab`.mimiciv_3_1_hosp.diagnoses_icd
    WHERE
        (icd_version = 9  AND (icd_code LIKE '480%' OR icd_code LIKE '481%'
                            OR icd_code LIKE '482%' OR icd_code LIKE '483%'
                            OR icd_code LIKE '484%' OR icd_code LIKE '485%'
                            OR icd_code LIKE '486%'))
        OR
        (icd_version = 10 AND (icd_code LIKE 'J12%' OR icd_code LIKE 'J13%'
                            OR icd_code LIKE 'J14%' OR icd_code LIKE 'J15%'
                            OR icd_code LIKE 'J16%' OR icd_code LIKE 'J17%'
                            OR icd_code LIKE 'J18%'))
    GROUP BY hadm_id
)
SELECT
    p.subject_id,
    p.gender,
    p.anchor_age          AS age,
    p.anchor_year_group,
    e.hadm_id,
    e.admittime,
    e.dischtime,
    e.los_days,
    e.admission_type,
    e.discharge_location,
    e.hospital_expire_flag,
    c.pneumonia_icd_codes
FROM er_admissions e
JOIN pneumonia_hadm      ph ON e.hadm_id = ph.hadm_id
JOIN pneumonia_codes_agg c  ON e.hadm_id = c.hadm_id
JOIN `cmi-lab`.mimiciv_3_1_hosp.patients p ON e.subject_id = p.subject_id
ORDER BY e.admittime
"""

print("Running query...")
df = client.query(sql).to_dataframe()
print(f"Rows     : {len(df):,}")
print(f"Patients : {df['subject_id'].nunique():,}")
print(f"Avg LOS  : {df['los_days'].mean():.1f} days")
print(f"Mortality: {df['hospital_expire_flag'].mean()*100:.1f}%")

output_path = '/Users/leesungmin/Desktop/graduate_school/2026_1/01_LYDUS_m4_mcp/claude-code-m4-result/er_pneumonia_cohort_260605.csv'
df.to_csv(output_path, index=False, encoding='utf-8-sig')
print(f"Saved: {output_path}")
