---
name: mimic-to-quiq
description: Convert MIMIC-IV clinical data into QUIQ (Quality Intelligence Unified Query) long-format table. Use when transforming MIMIC-IV tables to QUIQ format for data quality assessment, when applying QUIQ Mapping_info rules to MIMIC-IV variables, or when building a standardized long-format dataset from MIMIC-IV for quality management programs.
tier: community
category: system
---

# MIMIC-IV → QUIQ Format Conversion

Converts all MIMIC-IV tables (hosp, icu, ed schemas) into the QUIQ long-format table used by the LYDUS quality management program. Each original row becomes one or more QUIQ rows depending on table type (wide, code, or event).

## When to Use This Skill

- User asks to convert MIMIC-IV data to QUIQ format
- User wants to apply QUIQ Mapping_info rules to MIMIC-IV variables
- User needs a standardized long-format output for data quality assessment
- User references 가이드라인 제4권 §1.5 or QUIQ table structure

## QUIQ Table Schema

| Column | Description |
|--------|-------------|
| `Primary_key` | Row identifier (shared across rows from same original record) |
| `Variable_ID` | itemid for event tables, empty otherwise |
| `Original_table_name` | Source table (e.g., `ADMISSIONS`, `LABEVENTS`) |
| `Variable_name` | Column name or d_items/d_labitems label |
| `Event_date` | Measurement timestamp (NULL for non-event variables) |
| `Value` | String representation of the value |
| `Unit` | Unit of measurement |
| `Variable_type` | `timestamp` / `numeric` / `string` / `` (empty) |
| `Is_categorical` | `'1'` if categorical, `'0'` otherwise |
| `Recorder` | (empty in MIMIC) |
| `Recorder_position` | (empty in MIMIC) |
| `Recorder_affiliation` | (empty in MIMIC) |
| `Patient_id` | `subject_id` as STRING |
| `Admission_id` | `hadm_id` as STRING (empty for tables without hadm_id) |
| `Ground_truth` | (empty) |
| `Mapping_info_1` | Primary mapping category (see Mapping Rules) |
| `Mapping_info_2` | Secondary mapping subcategory |

## Mapping Rules (가이드라인 §1.5.2)

| Rule | Condition | Mapping_info_1 | Mapping_info_2 |
|------|-----------|----------------|----------------|
| 3 | Medical codes (ICD, NDC, GSN, HCPCS, DRG) | `medical_code` | NULL |
| 4 | Lab events | `event` | `lab_event` |
| 4 | Chart/vital events | `event` | `chart_event` |
| 4 | I&O events (input/output/ingredient) | `event` | NULL |
| 5 | Date/time columns | `date` | NULL |
| 6 | Diagnosis names (icd_title, chiefcomplaint) | `diagnosis` | NULL |
| 7 | Drug names (medication, drug, name) | `prescription` | `drug` |
| 7 | Prescription info (dose, route, frequency) | `prescription` | `prescription_info` |
| 8 | Procedure events (procedureevents) | `procedure` | NULL |
| — | All others | NULL | NULL |

## Conversion Strategy by Table Type

### ① Wide Tables (UNPIVOT)
Single row → multiple QUIQ rows (one per column). `Event_date = NULL`.
- **ADMISSIONS**: admittime/dischtime/deathtime → `date`
- **PATIENTS**: dod → `date`
- **TRANSFERS**: intime/outtime → `date`
- **EMAR**: medication → `prescription/drug`
- **PHARMACY**: medication → `prescription/drug`; route/frequency/dose → `prescription/prescription_info`
- **PRESCRIPTIONS**: drug → `prescription/drug`; gsn/ndc/formulary_drug_cd → `medical_code`
- **DIAGNOSES_ICD**: icd_code → `medical_code`
- **HCPCSEVENTS**: hcpcs_cd → `medical_code`; short_description → `procedure`

### ② Event Tables (base + all CTE pattern)
One original row → multiple QUIQ rows sharing the same Primary_key.

```
q_XXX_base: JOIN d_items/d_labitems → build all columns
q_XXX_all:  UNION ALL with _rtype ordering
  ① main value  → _m1, _m2 (lab/chart/event/procedure)
  ② date cols   → _m1='date', _m2=NULL
  ③ extra cols  → NULL, NULL
```

| Table | Main value column | _m1 | _m2 |
|-------|-------------------|-----|-----|
| LABEVENTS | value/valuenum | `event` | `lab_event` |
| CHARTEVENTS | value/valuenum | `event` | `chart_event` |
| DATETIMEEVENTS | value | `event` | `chart_event` |
| INGREDIENTEVENTS | amount | `event` | NULL |
| INPUTEVENTS | amount | `event` | NULL |
| OUTPUTEVENTS | value | `event` | NULL |
| PROCEDUREEVENTS | value | `procedure` | NULL |

### Event_date Assignment
- `Event_date = charttime or starttime` for the main measurement row
- `Event_date = NULL` for date columns written as rows (storetime, endtime, etc.)
- `Event_date = _ev` for secondary measurements tied to the same time (valuenum, warning, flag)

## BigQuery Implementation

The complete BigQuery SQL is in `scripts/bigquery.sql`. Key BigQuery differences from DuckDB:

| Feature | DuckDB (v5) | BigQuery |
|---------|-------------|---------|
| Functions | `CREATE MACRO` | `CREATE TEMP FUNCTION` |
| Type detection | `TRY_STRPTIME`, `TRY_CAST AS DOUBLE` | `SAFE.PARSE_TIMESTAMP`, `SAFE_CAST AS FLOAT64` |
| String type | `VARCHAR` | `STRING` |
| UNPIVOT | `INTO NAME k VALUE v` | `FOR k IN (cols)` |
| Reserved words | `"value"`, `"name"` | `` `value` ``, `` `name` `` |
| Table names | `hosp.admissions` | `mimiciv_hosp.admissions` |
| Output | `COPY (...) TO 'file.csv'` | Plain `SELECT` |

### How to run with M4 MCP

```python
from m4 import set_dataset, execute_query

set_dataset("mimic-iv")

with open("scripts/bigquery.sql") as f:
    sql = f.read()

df = execute_query(sql)
# Returns pd.DataFrame with all QUIQ columns
```

> **Note**: The SQL uses `CREATE TEMP FUNCTION` — BigQuery scripting mode must be enabled. M4's `execute_query()` supports multi-statement scripts.

## Critical Implementation Notes

1. **Primary_key is NOT globally unique** — it is unique only within each source table's CTE. The combination of `(Original_table_name, Primary_key)` uniquely identifies a source record.

2. **Event_date is selective** — Only clinically meaningful timestamps appear as `Event_date`. Administrative dates (admittime, storetime as standalone rows) use `Event_date = NULL` per §1.5.5.

3. **Empty string vs NULL** — `Value = ''` means the original field was NULL. Used as a filter: `WHERE raw_val IS NOT NULL` removes these in UNPIVOT-based tables.

4. **d_items JOIN** — ICU event tables use `COALESCE(di.label, CAST(itemid AS STRING))` so the Variable_name always has a human-readable label even if d_items has no matching row.

5. **_var_type detection order** — timestamp is checked before numeric. A value like `"2150-05-01 00:00:00"` is classified as `timestamp`, not `numeric`.

## References

- LYDUS 품질관리 프로그램 활용 가이드라인 제4권 §1.5~§1.6 (QUIQ table specification and Mapping rules)
- Johnson AEW et al. MIMIC-IV, a freely accessible electronic health record dataset. Sci Data. 2023;10:1.