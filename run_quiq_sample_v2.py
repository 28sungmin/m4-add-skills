from google.cloud import bigquery
import pandas as pd
import re
import os

client = bigquery.Client(project='cmi-lab-492906')

# 3명 subject_id 가져오기
print("Getting 3 sample subject_ids...")
sample_result = client.query(
    "SELECT subject_id FROM `cmi-lab`.mimiciv_3_1_hosp.patients ORDER BY RAND() LIMIT 3"
).to_dataframe()
sample_ids = sample_result['subject_id'].tolist()
ids_str = ', '.join(str(x) for x in sample_ids)
print(f"Subject IDs: {sample_ids}")

# SQL 읽기
sql_path = '/Users/leesungmin/Desktop/m4/src/m4/skills/system/quiq/scripts/bigquery.sql'
with open(sql_path) as f:
    sql = f.read()

sql = sql.replace('{bq_project}', 'cmi-lab')
sql = sql.replace('mimiciv_ed.', 'MIMIC_IV_ED.')

# 각 소스 테이블 FROM 절에 subject_id 필터 추가 (line-by-line)
skip_tables = {'d_items', 'd_labitems'}
lines = sql.split('\n')
new_lines = []
i = 0

while i < len(lines):
    line = lines[i]
    from_match = re.match(r'(\s+)FROM `cmi-lab`\.(\w+)\.(\w+)(\s+(\w+))?\s*$', line)

    if from_match:
        indent = from_match.group(1)
        table = from_match.group(3)
        alias = from_match.group(5)
        new_lines.append(line)

        if table not in skip_tables:
            # LEFT JOIN 라인들 먼저 수집해서 추가
            j = i + 1
            while j < len(lines) and re.match(r'\s+(LEFT\s+)?JOIN\s', lines[j]):
                new_lines.append(lines[j])
                j += 1

            # WHERE subject_id 필터 삽입
            if alias:
                new_lines.append(f'{indent}WHERE {alias}.subject_id IN ({ids_str})')
            else:
                new_lines.append(f'{indent}WHERE subject_id IN ({ids_str})')

            i = j
            continue

    new_lines.append(line)
    i += 1

filtered_sql = '\n'.join(new_lines)

# 쿼리 실행
print("Executing BigQuery query...")
job_config = bigquery.QueryJobConfig(use_query_cache=False)
job = client.query(filtered_sql, job_config=job_config)
df = job.to_dataframe()

print(f"Total rows: {len(df):,}")
print(f"Unique patients: {df['Patient_id'].nunique()}")
print(f"Tables covered: {df['Original_table_name'].nunique()}")
print(df.groupby('Original_table_name').size().to_string())

# CSV 저장
output_path = '/Users/leesungmin/Desktop/graduate_school/2026_1/01_LYDUS_m4_mcp/claude-code-m4-result/quiq_sample_260608.csv'
df.to_csv(output_path, index=False, encoding='utf-8-sig')
print(f"\nSaved: {output_path}")
