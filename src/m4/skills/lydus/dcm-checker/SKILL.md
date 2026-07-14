---
name: dcm-checker
description: Inspect DICOM (X-ray) header labels — verify presence/missingness of 21 clinically important header tags and compute a curation score (0-100). Use for LYDUS data quality assessment of DICOM imaging metadata before large-scale analysis.
tier: community
category: lydus
parameters:
  dcm_path:
    description: Path to a single DICOM file (.dcm).
    type: string
  threshold:
    description: Curation score below which the DICOM file is flagged as risky for research.
    default: 90
    type: integer
---

# LYDUS DICOM Checker

Inspects the **header-label quality of DICOM (X-ray) imaging data**: parses the DICOM header, checks which of **21 clinically important tags** are present vs missing, and assigns a **curation score (0-100)**. A low score means many missing labels that may cause trouble in large-scale analysis.

## When to Use This Skill

- Evaluating DICOM imaging metadata completeness before a large-scale imaging study
- Standardizing missing-header handling across a DICOM dataset (LYDUS Smart Curation)
- Quick per-file curation scoring of a DICOM header

## Checked Tags (21)

21 of ~250 DICOM headers, selected for clinical/technical X-ray use and confirmed by clinicians/radiologists:

| Group,Element | Name | | Group,Element | Name |
|---|---|---|---|---|
| 0008,002A | Acquisition DateTime | | 0018,1147 | Field of View Shape |
| 0008,0060 | Modality | | 0018,1149 | Field of View Dimensions |
| 0008,0070 | Manufacturer | | 0018,1164 | Imager Pixel Spacing |
| 0008,1030 | Study Description | | 0018,5101 | View Position |
| 0008,103E | Series Description | | 0020,0060 | Laterality |
| 0010,0020 | Patient ID | | 0028,0004 | Photometric Interpretation |
| 0010,0040 | Patient's Sex | | 0028,0010 | Rows |
| 0010,1010 | Patient's Age | | 0028,0011 | Columns |
| 0018,0015 | Body Part Examined | | 0028,0030 | Pixel Spacing |
| 0018,1000 | Device Serial Number | | 0028,0106 | Smallest Image Pixel Value |
| | | | 0028,0107 | Largest Image Pixel Value |

## Scoring

```
curation_score = int( present / 21 * 100 )   # 0-100
```

A tag is **present** if it exists in the header and its value is non-empty; otherwise **missing**.

## Auto-fill (described but not implemented)

The abstract describes auto-filling missing labels that can be derived from other fields (e.g., Patient's Age from Birth Date + Study Date). This is **not implemented in the original code (v1.0.6)** — the shipped tool only checks presence/missingness — so this skill does **not** implement it either, staying faithful to the source. It is noted here only so the gap between the abstract and the code is explicit.

## SQL Support

**Not applicable.** Operates on raw DICOM files, not a QUIQ table.

## How to Run

`scripts/dcm_checker.py` is a **headless** reimplementation of the original PyQt5 GUI, preserving the same 21-tag set and score formula, using `pydicom` for portability. (The original GUI is not vendored — see PROVENANCE.yaml for the source repo.)

```python
from scripts.dcm_checker import get_curation_score, format_report

result = get_curation_score("/path/to/image.dcm")
print(format_report(result, threshold=90))
# result["curation_score"], result["missing"], result["present"]
```

Or as a CLI:

```bash
python scripts/dcm_checker.py --dcm_path /path/to/image.dcm --threshold 90
```

## Critical Notes

1. **Faithful to the original — no auto-fill.** The abstract describes auto-filling derivable labels, but the shipped `program.py` (v1.0.6) only checks presence/missingness. This skill keeps that behavior; `dcm_checker.py` is a headless refactor of the same logic. This slimmed skill ships only `dcm_checker.py` (the original PyQt5 GUI is not vendored).

2. **Library choice.** The original GUI reads DICOM via SimpleITK (metadata keys like `0010|1010`). The headless version uses `pydicom` (tags like `(0x0010,0x1010)`) — more standard and testable. The 21-tag set and `int(present/21*100)` formula are identical, so scores match.

3. **Presence only for range/type.** The reference says "data type and data range will be considered," but v1.0.6 checks presence/missingness only. Range/type validation is not implemented.

4. **Single file per run.** v1.0.6 scores one DICOM file at a time. Multi-file batch analysis and integrated visualization are planned but not yet implemented.

5. **Threshold.** The reference flags files scoring below **90** (the default here).

6. **Pixel data / image rendering.** `load_dicom` reads headers only (`stop_before_pixels=True`) for speed. The original GUI also renders the image (SimpleITK + Qt); that display step is intentionally omitted from the headless checker.

## References

- LYDUS-DCM-Checker: https://github.com/Impku/LYDUS-DCM-Checker
- Cho SW, Han S, Hong N. "DCM-Checker" v1.0.6, Bonecentriq (Yonsei University), 2022.
- DICOM PS3.6 data dictionary (tag definitions).
