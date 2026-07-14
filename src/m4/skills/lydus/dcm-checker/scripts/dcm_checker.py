"""
LYDUS DICOM Checker — headless

DICOM(X-ray) 헤더 라벨 큐레이션 품질 검사. 임상/기술적으로 중요한 21개 DICOM 헤더
태그의 존재/결측을 확인하고 curation score(0-100)를 산출한다.

원본 PyQt5 GUI의 로직을 GUI 없이 호출 가능하도록 분리한 버전 (원본 저장소는 PROVENANCE 참조).
검사 대상 21개 태그와 int(truth/21*100) 점수식은 원본과 동일하게 유지했다.
DICOM 파싱은 이식성을 위해 pydicom을 사용한다(원본은 SimpleITK).

주의: abstract에는 결측 라벨 auto-fill 기능이 기술돼 있으나, 원본 코드(v1.0.6)에는
구현돼 있지 않아 이 버전에서도 구현하지 않는다(존재/결측 검사만 수행).
"""
from typing import Dict, List, Tuple

# 검사 대상 21개 태그: (group, element) → 표시 이름
# (원본 GUI thread.run 의 metadata 목록과 동일한 21개)
TAGS: List[Tuple[Tuple[int, int], str]] = [
    ((0x0008, 0x002A), "Acquisition DateTime"),
    ((0x0008, 0x0060), "Modality"),
    ((0x0008, 0x0070), "Manufacturer"),
    ((0x0008, 0x1030), "Study Description"),
    ((0x0008, 0x103E), "Series Description"),
    ((0x0010, 0x0020), "Patient ID"),
    ((0x0010, 0x0040), "Patient's Sex"),
    ((0x0010, 0x1010), "Patient's Age"),
    ((0x0018, 0x0015), "Body Part Examined"),
    ((0x0018, 0x1000), "Device Serial Number"),
    ((0x0018, 0x1147), "Field of View Shape"),
    ((0x0018, 0x1149), "Field of View Dimensions"),
    ((0x0018, 0x1164), "Imager Pixel Spacing"),
    ((0x0018, 0x5101), "View Position"),
    ((0x0020, 0x0060), "Laterality"),
    ((0x0028, 0x0004), "Photometric Interpretation"),
    ((0x0028, 0x0010), "Rows"),
    ((0x0028, 0x0011), "Columns"),
    ((0x0028, 0x0030), "Pixel Spacing"),
    ((0x0028, 0x0106), "Smallest Image Pixel Value"),
    ((0x0028, 0x0107), "Largest Image Pixel Value"),
]

N_TAGS = len(TAGS)  # 21


def load_dicom(path: str):
    """DICOM 파일을 읽는다 (pydicom). 픽셀 데이터는 읽지 않아 빠르다."""
    import pydicom

    return pydicom.dcmread(path, stop_before_pixels=True, force=True)


def _value(ds, tag: Tuple[int, int]):
    """태그 값을 반환. 없거나 빈 값이면 None. (원본: 태그 존재 + 값 != '')"""
    if tag not in ds:
        return None
    val = ds[tag].value
    if val is None or (isinstance(val, str) and val.strip() == ""):
        return None
    return val


def check_dicom(ds) -> Dict:
    """
    DICOM dataset의 21개 태그 존재/결측을 검사하고 curation score를 산출.

    Returns:
        {
          "curation_score": int(0-100),
          "n_present": int, "n_missing": int, "n_total": 21,
          "present": {name: value, ...},
          "missing": [name, ...],
        }
    """
    present: Dict[str, object] = {}
    missing: List[str] = []

    for tag, name in TAGS:
        val = _value(ds, tag)
        if val is not None:
            present[name] = val
        else:
            missing.append(name)

    n_present = len(present)
    # 원본: int((truth / 21) * 100)  (태그가 항상 21개이므로 truth/total 과 동일)
    score = int((n_present / N_TAGS) * 100)

    return {
        "curation_score": score,
        "n_present": n_present,
        "n_missing": len(missing),
        "n_total": N_TAGS,
        "present": present,
        "missing": missing,
    }


def get_curation_score(path: str) -> Dict:
    """파일 경로 → 검사 결과. (load_dicom + check_dicom 편의 래퍼)"""
    return check_dicom(load_dicom(path))


def format_report(result: Dict, threshold: int = 90) -> str:
    """검사 결과를 사람이 읽을 텍스트 리포트로 포맷."""
    lines = []
    lines.append("=" * 60)
    lines.append("LYDUS DICOM CHECKER — Curation Report")
    lines.append("=" * 60)
    score = result["curation_score"]
    flag = "⚠ below threshold" if score < threshold else "OK"
    lines.append(f"Curation score : {score} / 100   ({flag}, threshold={threshold})")
    lines.append(f"Present / Total : {result['n_present']} / {result['n_total']}")
    lines.append(f"Missing labels  : {result['n_missing']}")
    if result["missing"]:
        lines.append("\n[Missing]")
        for name in result["missing"]:
            lines.append(f"  - {name}")
    lines.append("\n" + "=" * 60)
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LYDUS DICOM label curation checker (headless)")
    parser.add_argument("--dcm_path", required=True, help="DICOM 파일 (.dcm)")
    parser.add_argument("--threshold", type=int, default=90, help="경고 임계 점수 (기본 90)")
    args = parser.parse_args()

    result = get_curation_score(args.dcm_path)
    print(format_report(result, threshold=args.threshold))
