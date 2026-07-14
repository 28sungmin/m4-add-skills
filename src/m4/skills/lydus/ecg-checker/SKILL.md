---
name: ecg-checker
description: Check the label-curation quality of GE MUSE ECG exports — verify presence/missingness of 35 ECG header attributes (3 classes) and compute a curation score (0-100), optionally rendering the 12-lead waveform. Use for LYDUS data quality assessment of ECG-derived labels before large-scale analysis.
tier: community
category: lydus
parameters:
  ecg_path:
    description: Path to a single GE MUSE ECG export file (.tsv/.csv). Tab separator recommended (label values may contain commas).
    type: string
  encoding:
    description: File encoding. GE MUSE Korean exports use cp949; UTF-8 exports use 'utf-8'.
    default: cp949
    type: string
  threshold:
    description: Curation score below which the ECG record is flagged as risky for research.
    default: 85
    type: integer
---

# LYDUS ECG Checker

Verifies the **label-curation quality of GE MUSE ECG data** by parsing the embedded header attributes of a single ECG export, checking which of 35 attributes are present vs missing, and assigning a **curation score (0-100)**. A low score means the record has many missing labels and may cause trouble in large-scale analysis.

## When to Use This Skill

- Filtering ECG records by label completeness before a large-scale ECG study
- Applying consistent missing-value criteria to GE MUSE–derived ECG data
- Quick per-file curation scoring of an ECG export (LYDUS Smart Curation)

## Attribute Classes (35 checked)

The reference schema lists 38 GE MUSE attributes; the checker evaluates **35** across three nesting levels:

| Class | Where | Count | Attributes |
|-------|-------|-------|------------|
| class1 | top-level columns | 12 | AlsUnitNo, Examdt, VentricularRate, PRInterval, QRSDuration, QTInterval, QTCorrected, PAxis, RAxis, TAxis, Diagnosis, RestingECG.Diagnosis.DiagnosisStatement |
| class2 | `Waveform` dict keys | 9 | WaveformType, WaveformStartTime, NumberofLeads, SampleType, SampleBase, SampleExponent, HighPassFilter, LowPassFilter, ACFilter |
| class3 | `Waveform.LeadData[0]` keys | 14 | LeadByteCountTotal, LeadTimeOffset, LeadSampleCountTotal, LeadAmplitudeUnitsPerBit, LeadAmplitudeUnits, LeadHighLimit, LeadLowLimit, LeadID, LeadOffsetFirstSample, FirstSampleBaseline, LeadSampleSize, LeadOff, BaselineSway, LeadDataCRC32 |

The `Waveform` column holds a Python-literal structure; the checker parses `literal_eval(Waveform)[1]` (the rhythm waveform) and its `LeadData[0]` (first lead).

## Scoring

```
curation_score = int( present / (present + missing) * 100 )   # 0-100
```

An attribute is **present** if its value is not `None` and not the string `"nan"`; otherwise **missing**. Records scoring below the threshold (default 85) are flagged. This version checks **presence/missingness only** — data type/range validation is described in the reference but not implemented in v1.0.3.

## SQL Support

**Not applicable.** Operates on raw GE MUSE ECG export files (TSV), not a QUIQ table.

## How to Run

`scripts/ecg_checker.py` is a **headless** refactor of the original PyQt5 GUI, exposing the same scoring logic without a display. (The original GUI is not vendored — see PROVENANCE.yaml for the source repo.)

```python
from scripts.ecg_checker import get_curation_score, format_report

result = get_curation_score("/path/to/ecg.tsv", encoding="cp949")
print(format_report(result, threshold=85))
# result["curation_score"], result["missing"], result["by_class"], result["present"]
```

Or as a CLI:

```bash
python scripts/ecg_checker.py --ecg_path /path/to/ecg.tsv --encoding cp949 --threshold 85
```

### Optional: render the 12-lead ECG image

```python
from scripts.ecg_checker import load_ecg, render_ecg_png
png_path = render_ecg_png(load_ecg("/path/to/ecg.tsv"))   # needs ecg_plot, numpy
```

Decodes the base64 `WaveFormData` of the 8 recorded leads and derives III/aVR/aVL/aVF to form a normalized 12-lead plot.

## Critical Notes

1. **Tab-separated input.** GE MUSE label values may contain commas, so a comma-delimited file mis-parses. Use tab (`\t`) — the default in `load_ecg`.

2. **Encoding.** GE MUSE Korean exports are `cp949`; the original GUI hardcodes this. UTF-8 exports need `encoding="utf-8"`.

3. **Single file per run.** v1.0.3 scores one ECG record at a time (the first data row). Multi-file batch analysis and aggregate visualization are planned but not yet implemented.

4. **Scale discrepancy.** The abstract mentions a 1,000,000-point scale, but the shipped code computes a **0-100** score; this skill follows the code. The reference README uses threshold 85; the original GUI splash text says 90 — this skill defaults to 85 and exposes it as a parameter.

5. **Headless only.** This slimmed skill ships just `ecg_checker.py` (importable, identical class lists and score formula). The original PyQt5 GUI is not vendored (it needs a display and is out of scope). Waveform parsing was made defensive (missing/unparseable `Waveform` → those attributes counted missing rather than crashing).

## References

- LYDUS-ECG-Checker: https://github.com/Impku/LYDUS-ECG-Checker
- Cho SW, Han S, Hong N. "ECG-Checker" v1.0.3, Bonecentriq (Yonsei University), 2022.
- GE MUSE ECG data format (38-attribute reference schema in repo README).
