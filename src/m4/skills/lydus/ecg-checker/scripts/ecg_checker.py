"""
LYDUS ECG Checker — headless

GE MUSE ECG 라벨 큐레이션 품질 검사. GE MUSE에서 export한 단일 ECG 레코드(TSV)의
헤더 속성(3개 class, 총 35개)이 존재/결측인지 확인하고 curation score(0-100)를 산출한다.

원본 PyQt5 GUI의 스코어링 로직을 GUI 없이 호출 가능하도록 분리한 버전 (원본 저장소는 PROVENANCE 참조).
스코어 계산과 class1/2/3 속성 목록은 원본과 동일하게 유지했다.
"""
from ast import literal_eval
from typing import Dict, List, Optional

import pandas as pd


# ============================================================
# 검사 대상 속성 (원본 GUI thread.run 과 동일)
# ============================================================

# class1: 레코드 최상위 컬럼에서 확인
CLASS1 = [
    "AlsUnitNo", "Examdt", "VentricularRate", "PRInterval", "QRSDuration",
    "QTInterval", "QTCorrected", "PAxis", "RAxis", "TAxis", "Diagnosis",
    "RestingECG.Diagnosis.DiagnosisStatement",
]

# class2: Waveform 딕셔너리 키에서 확인 (waveform = literal_eval(df['Waveform'][0])[1])
CLASS2 = [
    "WaveformType", "WaveformStartTime", "NumberofLeads", "SampleType",
    "SampleBase", "SampleExponent", "HighPassFilter", "LowPassFilter", "ACFilter",
]

# class3: LeadData[0] 딕셔너리 키에서 확인 (lead_data = waveform['LeadData'][0])
CLASS3 = [
    "LeadByteCountTotal", "LeadTimeOffset", "LeadSampleCountTotal",
    "LeadAmplitudeUnitsPerBit", "LeadAmplitudeUnits", "LeadHighLimit",
    "LeadLowLimit", "LeadID", "LeadOffsetFirstSample", "FirstSampleBaseline",
    "LeadSampleSize", "LeadOff", "BaselineSway", "LeadDataCRC32",
]


def load_ecg(path: str, encoding: str = "cp949", sep: str = "\t") -> pd.DataFrame:
    """
    GE MUSE ECG export 파일을 읽는다.

    Args:
        path: ECG 파일 경로 (.tsv / .csv)
        encoding: 파일 인코딩. GE MUSE 한국어 export는 cp949. UTF-8이면 'utf-8'.
        sep: 컬럼 구분자. 라벨 값 안에 콤마가 들어갈 수 있어 탭('\\t') 권장.

    Returns:
        단일 ECG 레코드 DataFrame (첫 행만 사용)
    """
    return pd.read_csv(path, encoding=encoding, sep=sep)


def _present(value) -> bool:
    """값이 존재(비결측)하는지. 원본과 동일하게 None / 'nan' 문자열을 결측으로 본다."""
    return value is not None and str(value) != "nan"


def check_ecg(df: pd.DataFrame) -> Dict:
    """
    ECG DataFrame의 헤더 속성 존재/결측을 검사하고 curation score를 산출.

    Args:
        df: load_ecg 결과 (첫 행 = 하나의 ECG 레코드)

    Returns:
        {
          "curation_score": int(0-100),
          "n_present": int, "n_missing": int, "n_total": int,
          "present": {attr: value, ...},
          "missing": [attr, ...],
          "by_class": {"class1": {...}, "class2": {...}, "class3": {...}},
        }
    """
    present: Dict[str, object] = {}
    missing: List[str] = []
    by_class = {c: {"present": [], "missing": []} for c in ("class1", "class2", "class3")}

    # --- class1: 최상위 컬럼 ---
    for c in CLASS1:
        if c in df.columns and _present(df[c][0]):
            present[c] = df[c][0]
            by_class["class1"]["present"].append(c)
        else:
            missing.append(c)
            by_class["class1"]["missing"].append(c)

    # --- Waveform / LeadData 파싱 ---
    # 원본: waveform = literal_eval(df['Waveform'][0])[1]; lead_data = waveform['LeadData'][0]
    waveform: Dict = {}
    lead_data: Dict = {}
    if "Waveform" in df.columns and _present(df["Waveform"][0]):
        try:
            parsed = literal_eval(df["Waveform"][0])
            waveform = parsed[1] if isinstance(parsed, (list, tuple)) else parsed
            leads = waveform.get("LeadData", [])
            lead_data = leads[0] if leads else {}
        except (ValueError, SyntaxError, KeyError, IndexError, TypeError):
            waveform, lead_data = {}, {}

    # --- class2: Waveform 딕셔너리 키 ---
    for c in CLASS2:
        if c in waveform and _present(waveform[c]):
            present[c] = waveform[c]
            by_class["class2"]["present"].append(c)
        else:
            missing.append(c)
            by_class["class2"]["missing"].append(c)

    # --- class3: LeadData[0] 딕셔너리 키 ---
    for c in CLASS3:
        if c in lead_data and _present(lead_data[c]):
            present[c] = lead_data[c]
            by_class["class3"]["present"].append(c)
        else:
            missing.append(c)
            by_class["class3"]["missing"].append(c)

    n_present = len(present)
    n_missing = len(missing)
    n_total = n_present + n_missing
    # 원본: int((truth / (truth + false)) * 100)
    score = int((n_present / n_total) * 100) if n_total else 0

    return {
        "curation_score": score,
        "n_present": n_present,
        "n_missing": n_missing,
        "n_total": n_total,
        "present": present,
        "missing": missing,
        "by_class": by_class,
    }


def get_curation_score(path: str, encoding: str = "cp949", sep: str = "\t") -> Dict:
    """파일 경로 → 검사 결과. (load_ecg + check_ecg 편의 래퍼)"""
    return check_ecg(load_ecg(path, encoding=encoding, sep=sep))


def format_report(result: Dict, threshold: int = 85) -> str:
    """검사 결과를 사람이 읽을 텍스트 리포트로 포맷."""
    lines = []
    lines.append("=" * 60)
    lines.append("LYDUS ECG CHECKER — Curation Report")
    lines.append("=" * 60)
    score = result["curation_score"]
    flag = "⚠ below threshold" if score < threshold else "OK"
    lines.append(f"Curation score : {score} / 100   ({flag}, threshold={threshold})")
    lines.append(f"Present / Total : {result['n_present']} / {result['n_total']}")
    lines.append(f"Missing labels  : {result['n_missing']}")
    for cls in ("class1", "class2", "class3"):
        bc = result["by_class"][cls]
        lines.append(f"\n[{cls}] present {len(bc['present'])} / missing {len(bc['missing'])}")
        if bc["missing"]:
            lines.append("  missing: " + ", ".join(bc["missing"]))
    lines.append("\n" + "=" * 60)
    return "\n".join(lines)


# ============================================================
# (선택) 12-lead 파형 이미지 렌더링 — 원본 extract_leads + ecg_plot
# ============================================================

def extract_leads(df: pd.DataFrame) -> "pd.DataFrame":
    """
    Waveform LeadData(8 leads)의 base64 신호를 디코딩하여 12-lead DataFrame 생성.
    (원본 MyApp.extract_leads 와 동일: III/aVR/aVL/aVF는 8 lead에서 유도)
    """
    import array
    import base64

    import numpy as np

    lead_data = literal_eval(df["Waveform"][0])[1]["LeadData"]
    result: Dict[str, object] = {}
    for x in lead_data:
        decoded = base64.b64decode(x["WaveFormData"])
        signal = np.array(array.array("h", decoded))
        laupb = float(x["LeadAmplitudeUnitsPerBit"])
        result[x["LeadID"]] = (signal * laupb) / 1000

    result["III"] = np.subtract(result["II"], result["I"])
    result["aVR"] = np.add(result["I"], result["II"]) * (-0.5)
    result["aVL"] = np.subtract(result["I"], 0.5 * result["II"])
    result["aVF"] = np.subtract(result["II"], 0.5 * result["I"])
    return pd.DataFrame.from_dict(result)


def render_ecg_png(df: pd.DataFrame, out_dir: str = "tmp/", name: str = "example_ecg",
                   sample_rate: int = 500) -> str:
    """12-lead ECG를 PNG로 저장. ecg_plot 필요. 저장 경로 반환."""
    import ecg_plot

    lead_df = extract_leads(df)
    for col in lead_df.columns:
        lead_df[col] = (lead_df[col] - lead_df[col].mean()) / lead_df[col].std()
    ecg_plot.plot_12(lead_df.T.values, sample_rate=sample_rate,
                     lead_index=lead_df.columns, columns=1, title="")
    ecg_plot.save_as_png(name, out_dir)
    return f"{out_dir}{name}.png"


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LYDUS ECG label curation checker (headless)")
    parser.add_argument("--ecg_path", required=True, help="GE MUSE ECG export 파일 (.tsv/.csv)")
    parser.add_argument("--encoding", default="cp949", help="파일 인코딩 (기본 cp949)")
    parser.add_argument("--sep", default="\t", help="컬럼 구분자 (기본 탭)")
    parser.add_argument("--threshold", type=int, default=85, help="경고 임계 점수 (기본 85)")
    args = parser.parse_args()

    result = get_curation_score(args.ecg_path, encoding=args.encoding, sep=args.sep)
    print(format_report(result, threshold=args.threshold))
