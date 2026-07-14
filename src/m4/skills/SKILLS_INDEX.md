# M4 Skills Index

This directory contains skills for the M4 framework, covering clinical research concepts and system functionality.

## Clinical Skills

### Severity Scores

| Skill | Description |
|-------|-------------|
| [sofa-score](clinical/sofa-score/SKILL.md) | Sequential Organ Failure Assessment score calculation |
| [apache-iv-score](clinical/apache-iv-score/SKILL.md) | APACHE IV with mortality prediction |
| [apsiii-score](clinical/apsiii-score/SKILL.md) | APACHE III (Acute Physiology Score III) with mortality prediction |
| [sapsii-score](clinical/sapsii-score/SKILL.md) | SAPS-II score with mortality prediction |
| [oasis-score](clinical/oasis-score/SKILL.md) | Oxford Acute Severity of Illness Score (no labs required) |
| [lods-score](clinical/lods-score/SKILL.md) | Logistic Organ Dysfunction Score |
| [sirs-criteria](clinical/sirs-criteria/SKILL.md) | Systemic Inflammatory Response Syndrome criteria |
| [hfrs](clinical/hfrs/SKILL.md) | Hospital Frailty Risk Score from ICD codes (Gilbert 2018) |
| [comorbidity-score](clinical/comorbidity-score/SKILL.md) | Charlson and Elixhauser comorbidity indices for risk adjustment |

### Sepsis and Infection

| Skill | Description |
|-------|-------------|
| [sepsis-3-cohort](clinical/sepsis-3-cohort/SKILL.md) | Sepsis-3 cohort identification (SOFA >= 2 + infection) |
| [suspicion-of-infection](clinical/suspicion-of-infection/SKILL.md) | Suspected infection events (antibiotic + culture) |

### Organ Failure

| Skill | Description |
|-------|-------------|
| [kdigo-aki-staging](clinical/kdigo-aki-staging/SKILL.md) | KDIGO AKI staging using creatinine and urine output |
| [meld-score](clinical/meld-score/SKILL.md) | MELD score for liver disease severity and transplant prioritization |

### Medications and Treatments

| Skill | Description |
|-------|-------------|
| [vasopressor-equivalents](clinical/vasopressor-equivalents/SKILL.md) | Norepinephrine-equivalent dose calculation |
| [ventilation-classification](clinical/ventilation-classification/SKILL.md) | Ventilation status classification and episode detection |

### Laboratory and Measurements

| Skill | Description |
|-------|-------------|
| [baseline-creatinine](clinical/baseline-creatinine/SKILL.md) | Baseline creatinine estimation for AKI staging |
| [gcs-calculation](clinical/gcs-calculation/SKILL.md) | Glasgow Coma Scale extraction with intubation handling |

### Cohort Definitions

| Skill | Description |
|-------|-------------|
| [first-icu-stay](clinical/first-icu-stay/SKILL.md) | First ICU stay selection and cohort construction |

### Research Methodology

| Skill | Description |
|-------|-------------|
| [clinical-research-pitfalls](clinical/clinical-research-pitfalls/SKILL.md) | Common methodological mistakes and how to avoid them |
| [clinical-research-analysis-framework](clinical/clinical-research-analysis-framework/SKILL.md) | Guided statistical/ML analysis workflow with structured consultation and audit trails |
| [equiflow](clinical/equiflow/SKILL.md) | Equity-focused cohort flow diagrams with SMD bias detection (Ellen 2024) |

## Lydus Skills

### Data Quality

| Skill | Description |
|-------|-------------|
| [quiq](lydus/quiq/SKILL.md) | Convert MIMIC-IV tables to QUIQ long-format for LYDUS data quality assessment (가이드라인 §1.5) |
| [class-diversity](lydus/class-diversity/SKILL.md) | Calculate Simpson class diversity per categorical variable in a QUIQ table |
| [classification](lydus/classification/SKILL.md) | Calculate classification metrics (Accuracy, Precision, Recall, F1, AUROC) per variable in a QUIQ table with Ground_truth labels |
| [completeness](lydus/completeness/SKILL.md) | Calculate data completeness (non-null rate) per variable in a QUIQ table |
| [cross-sectional-consistency](lydus/cross-sectional-consistency/SKILL.md) | Calculate cross-sectional consistency using Claude CLI to group semantically equivalent values per variable; no API key required |
| [date-validity](lydus/date-validity/SKILL.md) | Validate date values in a QUIQ table (Event_date + Mapping_info_1=date rows) using standard parsing, Korean formats, and optional LLM fallback |
| [deid-clinical-notes](lydus/deid-clinical-notes/SKILL.md) | Detect and tag PHI/PII in Korean clinical free-text using regex rules (7 active label types; sensitive-diagnosis rules ship but off by default), wrapping matches as &lt;LABEL&gt;string&lt;/LABEL&gt; for de-identification |
| [dcm-checker](lydus/dcm-checker/SKILL.md) | Inspect DICOM (X-ray) header labels — check presence of 21 clinically important tags and compute a 0-100 curation score |
| [ecg-checker](lydus/ecg-checker/SKILL.md) | Check GE MUSE ECG export label completeness (35 header attributes, 3 classes) and compute a 0-100 curation score, with optional 12-lead waveform rendering |
| [fidelity](lydus/fidelity/SKILL.md) | Calculate structured fidelity (per-patient recording frequency) for event/diagnosis/prescription/procedure variables in a QUIQ table |
| [format-validity](lydus/format-validity/SKILL.md) | Validate format of medical codes (ICD-9/10/11, SNOMED-CT, RxNorm, LOINC, ATC) in a QUIQ table using regex, with optional LLM fallback for unknown code types |
| [instance-diversity](lydus/instance-diversity/SKILL.md) | Calculate instance diversity and Gini-Simpson index per (variable, value) in a QUIQ table — measures how evenly distributed patients are across occurrences of each clinical value |
| [logical-accuracy](lydus/logical-accuracy/SKILL.md) | Detect logical outliers in clinical variables using Quantile Regression + GBR + Autoencoder (numeric) or OneClassSVM + IsolationForest + Autoencoder (categorical); uses Claude CLI, no API key required |
| [note-accuracy](lydus/note-accuracy/SKILL.md) | Evaluate accuracy of unstructured clinical notes (note_clinical) and radiology reports (note_rad) using Claude CLI error detection; no API key required |
| [note-fidelity](lydus/note-fidelity/SKILL.md) | Evaluate completeness of clinical notes and radiology reports by checking whether required template items are mentioned via Claude CLI; no API key required |
| [preciseness](lydus/preciseness/SKILL.md) | Calculate decimal-place consistency of numeric variables using iterative scale detection and Gini-Simpson last-digit diversity; no API key required |
| [range-validity](lydus/range-validity/SKILL.md) | Detect IQR outliers (1.5×IQR Tukey fence) in numeric variables and compute Range Validity (%); SQL (DuckDB PERCENTILE_CONT) + Python with boxplots |
| [sentence-diversity](lydus/sentence-diversity/SKILL.md) | Measure diversity of verb-containing sentences in clinical notes using NLTK POS tagging; computes unique/total ratio and top-5/10/20% coverage scores |
| [sequence-validity](lydus/sequence-validity/SKILL.md) | Validate chronological ordering of date variable pairs (start ≤ end) in a QUIQ table; Claude CLI auto-identifies pairs, no API key required |
| [time-series-consistency](lydus/time-series-consistency/SKILL.md) | Detect temporal distribution shifts (change points) across years using GradientBoosting AUROC + SHAP; no API key required |
| [vocabulary-diversity](lydus/vocabulary-diversity/SKILL.md) | Measure diversity of noun words in clinical notes using NLTK POS tagging; computes unique/total noun ratio and top-5/10/20% coverage scores |
| [bias-detection](lydus/bias-detection/SKILL.md) | Detect demographic bias by running all 16 LYDUS quality metrics per Sex/Race/Age group and computing GDI (Group Disparity Index); uses Claude CLI, no API key required |

## System Skills

### Data Structure

| Skill | Description |
|-------|-------------|
| [mimic-table-relationships](system/mimic-table-relationships/SKILL.md) | MIMIC-IV table relationships and join patterns |
| [mimic-eicu-mapping](system/mimic-eicu-mapping/SKILL.md) | Mapping between MIMIC-IV and eICU databases |

### M4 Framework

| Skill | Description |
|-------|-------------|
| [m4-api](system/m4-api/SKILL.md) | Python API for M4 clinical data queries |
| [clinical-research-session](system/clinical-research-session/SKILL.md) | Structured clinical research workflow and protocol drafting |
| [m4-setup](system/m4-setup/SKILL.md) | Diagnose and repair M4 environment, dataset, skill, backend, and vitrine setup issues |
| [vitrine-api](system/vitrine-api/SKILL.md) | Vitrine display API for visualizations, forms, approvals, study tracking, and exports |
| [create-m4-skill](system/create-m4-skill/SKILL.md) | Guide for creating new M4 skills |

---

## Gaps and Future Work

### Candidate Skills Not Yet Ported

The following valuable concepts exist in source repositories or clinical workflows but have not yet been converted into M4 skills:

| Priority | Candidate Skill | Rationale |
|----------|-----------------|-----------|
| High | **Ventilation Duration** | Common ICU exposure/outcome; episode logic, gaps, tracheostomy, NIV, and HFNC handling are easy to misuse. |
| High | **Antibiotic Classification** | Needed for infection, sepsis, and stewardship studies; drug naming and class/spectrum mapping require curated logic. |
| High | **CRRT Concepts** | Important for AKI, shock, severity scoring, and renal replacement adjustment; timing and modality distinctions matter. |
| Medium | **Code Status** | DNR/DNI and comfort-care documentation can affect mortality analyses, but extraction is often institution-specific and incomplete. |
| Medium | **APACHE-II Score** | Clinically recognizable historical score, but lower priority because M4 already includes newer severity scores. |

### eICU-Specific Concepts Needed

- APACHE IV (pre-computed in eICU)
- eICU pivoted lab values
- eICU vasopressor concepts
- Hospital-level clustering

### Additional Data Quality Skills

- Unit conversion guidelines
- Outlier detection thresholds
- Timestamp and time zone handling

---

## Usage Notes

1. **Dataset-Agnostic Design**: Skills document concepts, not dataset-specific implementations. Dataset-specific SQL lives in each skill's `scripts/` subdirectory.

2. **Pre-computed Tables**: Most clinical skills reference pre-computed derived tables in `mimiciv_derived` schema. These are available on BigQuery and can be regenerated locally via `m4 init-derived`.

3. **Script Files**: Full SQL implementations are in each skill's `scripts/` subdirectory, with separate files per dataset where applicable.

4. **Format Reference**: See [SKILL_FORMAT.md](SKILL_FORMAT.md) for the canonical skill structure specification.

---

## References

- MIMIC-IV: https://mimic.mit.edu/docs/iv/
- eICU: https://eicu-crd.mit.edu/
- mimic-code: https://github.com/MIT-LCP/mimic-code
- eicu-code: https://github.com/MIT-LCP/eicu-code
- Agent Skills Standard: https://agentskills.io