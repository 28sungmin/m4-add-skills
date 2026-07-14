---
name: deid-clinical-notes
description: Detect and label de-identification–target personal information (names, IDs, addresses, dates/times/periods, other hospitals) in unstructured Korean clinical notes using regular-expression rules, wrapping each match as <LABEL>string</LABEL>. Sensitive-diagnosis rules (KCD/name) ship but are off by default. Use for LYDUS pseudonymization/de-identification of free-text medical records.
tier: community
category: lydus
parameters:
  text:
    description: Free text (or path to a .txt file) to label. Alternatively use csv+column for a CSV column.
    type: string
  configs:
    description: List of YAML config files defining the regex rules. Default = disease_kcd + disease_name + smc.
    type: array
---

# De-identification Labeling for Korean Clinical Notes

Automatically detects **de-identification–target information** in unstructured Korean free-text medical records using regular-expression rules, and wraps each detected span as `<LABEL>string</LABEL>`. Based on the MOHW Medical Data Utilization Guidelines and Samsung Medical Center internal policy; the regex rules were derived from how these identifiers actually appear in real records.

```
input : 24.08.01 퇴원 후 hemoptysis 발생
output: <DATE>24.08.01</DATE> 퇴원 후 hemoptysis 발생
```

## When to Use This Skill

- Pre-processing Korean clinical notes for pseudonymization / de-identification before analysis or model training
- Detecting PHI/PII and sensitive diagnoses in free-text EHR columns
- Building fully de-identified training datasets from unstructured records (LYDUS Smart Curation)

## Label Types

The abstract lists 15 label types, but in the **shipped `smc.yml` only 7 are active** — the rest are present but commented out in the `items:` list (verified: the parsed config registers exactly these 7):

| Category | Active labels (7) |
|----------|-----------------|
| Identity | `NAME`, `IDENTIFICATION_NUMBER` (+ KONOS_ID, SURGICAL_ID subtypes), `ADDRESS` |
| Temporal | `DATE`, `TIME`, `PERIOD` |
| Institution | `OTHER_HOSPITAL` |

**Commented out (not produced unless enabled):** `AGE`, `DATETIME`, and all six sensitive-diagnosis labels `DISEASE_SEXUAL`, `DISEASE_AIDS`, `DISEASE_ABORTION`, `DISEASE_ABUSE`, `DISEASE_MENTAL`, `DISEASE_RARE`. To enable a label, uncomment its block under `items:` in `config/smc.yml`.

The disease rules themselves are shipped: sensitive diagnoses can be detected two ways once enabled — by **KCD code** (`config/disease_kcd.yml`) and by **diagnosis name** in Korean/English (`config/disease_name.yml`, ~2600 entries) — but the `items:` entries that wire them in (`DISEASE_*`, referencing `*sdz_*_kcd` / `*sdz_*_name`) are commented out by default.

## Config Structure (`config/*.yml`)

- `alias:` — reusable regex fragments referenced as `${name}` (e.g. `c_ymd` = year-month-day). Aliases may nest but must not loop.
- `items:` — the label definitions; each maps a label (e.g. `DATE`) to one or more named patterns (`DATE__YMD`, `DATE__MD`, …). Longer/more-specific patterns are placed first (PERIOD → DATETIME → DATE → TIME) so they match before shorter ones.
- `exception:` per pattern — a match that also matches the exception is left untagged (to suppress false positives like lab values that look like dates).
- `company: SMC` → output tag is `<ITEM>…</ITEM>`; otherwise `<deid item="ITEM">…</deid>`.
- Regexes use the `regex` module (not `re`) and are compiled case-insensitively (`rx.I`). Named groups must start with `__`.

## SQL Support

**Not applicable.** Operates on raw free text / CSV columns, not a QUIQ table.

## How to Run

`scripts/deid_label.py` is a **headless** runner that reuses the original rule engine (`load_config` / `make_alias` / `get_patterns` / `make_pattern` / `add_label`, copied verbatim from the upstream tool's `fns/label.py`).

```python
from scripts.deid_label import label_text, label_csv_column

configs = [
    "scripts/config/disease_kcd.yml",
    "scripts/config/disease_name.yml",
    "scripts/config/smc.yml",
]
print(label_text("2024.01.10 삼성서울병원 11pm 내원", configs))
# <DATE>2024.01.10</DATE> <OTHER_HOSPITAL>삼성서울병원</OTHER_HOSPITAL> <TIME>11pm</TIME> 내원

# a CSV column:
label_csv_column("notes.csv", "현병력", configs, out_path="notes_deid.csv")
```

CLI (run from `scripts/`):

```bash
python deid_label.py --text "24.08.01 퇴원 후 hemoptysis 발생"
python deid_label.py --in_file note.txt --out note_deid.txt
python deid_label.py --csv notes.csv --column 현병력 --out notes_deid.csv
```

Dependencies: `regex`, `PyYAML` (+ `pandas` for CSV). Config order matters — pass disease configs before `smc.yml`.

## Other Tool Features (upstream, not shipped here)

The original tool also provides (per the abstract) four auxiliary text-analysis features: label review via `view_tag.html`, regex string search (`fns/grep.py`), column extraction (`fns/column2txt.py`), and file comparison (`fns/compare.py`). These are **not vendored** in this slimmed skill, which focuses on the de-identification labeling (feature #1). Get them from the upstream repo (see PROVENANCE.yaml) if needed.

## Critical Notes

1. **Only 7 labels active (not 15).** The shipped `smc.yml` has just 7 uncommented `items:` (NAME, IDENTIFICATION_NUMBER, ADDRESS, DATE, TIME, PERIOD, OTHER_HOSPITAL). `AGE`, `DATETIME`, and all six `DISEASE_*` sensitive-diagnosis labels exist in the config (and their rules ship in `disease_*.yml`) but are **commented out**, so sensitive-diagnosis detection does **not** fire by default. Uncomment the relevant `items:` blocks in `config/smc.yml` to enable them.

2. **Headless runner vs original `label.py`.** The upstream `fns/label.py` `main()` was refactored to serve a Doccano REST endpoint (`predictREGEX`, takes a text string, no `__main__`, applies extra BIO/tokenization post-processing, and references an undefined `parallel_processing_function`) — so the README's `python fns/label.py config/smc.yml` CLI does not run cleanly as-is. `deid_label.py` copies the same rule-engine functions verbatim to give a working, faithful labeling interface. This skill is slimmed: only the config rules (`config/*.yml`) and `deid_label.py` are shipped; the original `fns/` and auxiliary utilities are not vendored (see PROVENANCE.yaml for the source repo).

3. **`company: SMC` tag format.** With `company: SMC`, tags are `<DATE>…</DATE>`; other companies get `<deid item="DATE">…</deid>`. Keep `company: SMC` for the label format in the abstract.

4. **Regex module.** Requires the third-party `regex` package (supports `\b(?-i:…)` inline flags used by the disease configs) — `re` will not compile these.

5. **Restricted content.** This is a `#Restricted` Samsung Medical Center tool; `disease_name.yml` encodes sensitive-diagnosis terms. Detection is regex-based (recall is not guaranteed) — treat output as an assistive first pass for de-identification, not a certified guarantee, and keep a human review step.

6. **Doccano / BERT.** The repo also ships a Doccano auto-labeling integration and a separate `bert_pipeline/` (KoBERT de-identification). This skill covers the regex pipeline described in the abstract; the BERT pipeline is out of scope here.

## References

- SHL-Curation-Tool: https://github.com/SmartHealthLab/SHL-Curation-Tool
- Ministry of Health and Welfare. "Medical Data Utilization Guidelines" (의료데이터 활용 가이드라인), 2022-12-28.
- Aguirre J. "Samsung Medical Center Regex Curation Tool", Smart Health Lab, 2023.
