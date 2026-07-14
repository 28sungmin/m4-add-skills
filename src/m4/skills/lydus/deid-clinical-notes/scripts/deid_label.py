"""
Headless PHI/PII de-identification labeler for Korean clinical notes.

Applies the regex rules defined in the YAML config files (config/smc.yml,
config/disease_kcd.yml, config/disease_name.yml) to free text and wraps detected
personal/sensitive information in <LABEL>string</LABEL> tags.

Note: this slimmed skill ships only the config rules and this self-contained runner.
The original tool's fns/ implementation and auxiliary utilities (grep, column2txt,
compare, view_tag.html) are not vendored — see the upstream repo in PROVENANCE.yaml.

Example:
    input : '24.08.01 퇴원 후 hemoptysis 발생'
    output: '<DATE>24.08.01</DATE> 퇴원 후 hemoptysis 발생'

The core labeling functions below (load_config, make_alias, get_patterns,
make_pattern, add_label, find_pattern, test_patterns) are copied VERBATIM from the
upstream tool's fns/label.py. They are self-contained (only need `regex` + `PyYAML`).
This runner exists because the original fns/label.py main()/CLI was refactored to
serve a Doccano REST endpoint (takes a text string, has no __main__, and applies
BIO post-processing) — this script gives a clean, faithful CLI/function for the
labeling behavior described in the tool's abstract, reusing the same rule engine.
"""
import argparse
import sys
from pathlib import Path

import regex as rx
import yaml


# ============================================================
# 아래 함수들은 원본 도구의 fns/label.py 에서 그대로 가져옴 (verbatim)
# ============================================================

def load_config(configs):
    yml = ''
    for config in configs:
        with open(config, encoding='utf-8') as f:
            yml += f.read() + '\n'
    return yaml.load(yml, Loader=yaml.FullLoader)


def find_pattern(pts, k, name='exception'):
    x = [p[k][name] for p in pts if k in p and name in p[k]]
    return x[0] if len(x) > 0 else None


def add_label(line, colname, pattern, pts, company, formaton, flog):
    def _rep(x):
        k, v = [(k, v) for k, v in x.groupdict().items() if v != None and not k.startswith('__')][0]

        ex = find_pattern(pts, k, 'exception')
        if ex is not None and rx.search(ex, v) is not None:
            return v

        it, nm = k.split('__', 1)
        if flog is not None:
            flog.write(f'\n{line}: {it}.{nm}: {v}')

        format_str = f' format="{nm}"' if formaton else ''
        if company == 'SMC':
            return f'<{it}{format_str}>{v}</{it}>'
        return f'<deid item="{it}"{format_str}>{v}</deid>'

    replaced = pattern.sub(_rep, line)
    return replaced


def make_alias(cfg):
    pattern = rx.compile(r'\$\{[_\w]+\}')

    def _rxp(x):
        k = x.group()[2:-1]
        if k not in cfg['alias']:
            raise KeyError(f'No alias: {k}')

        v = cfg['alias'][k]
        m = pattern.search(v)
        return v if m == None else pattern.sub(_rxp, v)

    for k, v in cfg['alias'].items():
        cfg['alias'][k] = pattern.sub(_rxp, v)
    return cfg


def get_patterns(cfg):
    _rxp = lambda x: cfg['alias'][x.group()[2:-1]]

    pattern = rx.compile(r'\$\{[_\w]+\}')

    rep = []
    for item in cfg['items']:
        it, fms = list(item.items())[0]
        for fm in fms:
            k, v = list(fm.items())[0]
            tmp = {}
            for x in ['pattern', 'exception']:
                if x not in v:
                    continue
                tmp[x] = pattern.sub(_rxp, v[x])
            rep.append({f'{it}__{k}': tmp})
    return rep


def make_pattern(rep):
    pts = []
    for item in rep:
        k, v = list(item.items())[0]
        pts.append(f'(?P<{k}>{v["pattern"]})')
    return '|'.join(pts)


def test_patterns(rep):
    for item in rep:
        k, v = list(item.items())[0]
        for x in ['pattern', 'exception']:
            if x not in v:
                continue
            try:
                rx.compile(f'(?P<{k}>{v[x]})', flags=rx.I)
            except rx.error as e:
                print(f'[E] {k}\n\t{x}: {v[x]}\n\t{e}')
                return False
    return True


# ============================================================
# Headless 실행 인터페이스
# ============================================================

def build_pattern(configs):
    """config 파일들을 읽어 (compiled_pattern, pts, company, formaton) 반환."""
    cfg = load_config(configs)
    company = cfg.get('company')
    formaton = cfg.get('format', False)
    cfg = make_alias(cfg)
    pts = get_patterns(cfg)
    if not test_patterns(pts):
        raise ValueError("Invalid regex pattern in config (see stderr).")
    pattern = rx.compile(make_pattern(pts), flags=rx.I)
    return pattern, pts, company, formaton


def label_text(text, configs, flog=None):
    """자유 텍스트에 PHI/PII 라벨을 삽입해 반환. (줄 단위로 add_label 적용)"""
    pattern, pts, company, formaton = build_pattern(configs)
    lines = text.split('\n')
    labeled = [add_label(line, 'text', pattern, pts, company, formaton, flog) for line in lines]
    return '\n'.join(labeled)


def label_csv_column(in_path, column, configs, out_path=None, encoding='utf-8'):
    """CSV의 한 컬럼(자유 텍스트)에 라벨을 삽입. 결과 DataFrame 반환(+선택 저장)."""
    import pandas as pd

    pattern, pts, company, formaton = build_pattern(configs)
    df = pd.read_csv(in_path, dtype=object, na_filter=False, encoding=encoding)
    if column not in df.columns:
        raise KeyError(f"Column '{column}' not found. Available: {list(df.columns)}")
    df[column] = df[column].map(
        lambda s: add_label(str(s), column, pattern, pts, company, formaton, None)
    )
    if out_path:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out_path, index=False, encoding=encoding)
    return df


_DEFAULT_CONFIGS = [
    "config/disease_kcd.yml",
    "config/disease_name.yml",
    "config/smc.yml",
]

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Korean clinical-note PHI/PII regex labeler (headless)")
    parser.add_argument("--configs", nargs="+", default=_DEFAULT_CONFIGS,
                        help="YAML config 파일들 (기본: disease_kcd + disease_name + smc)")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--text", help="라벨링할 텍스트 (직접 입력)")
    src.add_argument("--in_file", help="라벨링할 .txt 파일")
    src.add_argument("--csv", help="라벨링할 CSV 파일 (--column 필요)")
    parser.add_argument("--column", help="--csv 사용 시 대상 컬럼명")
    parser.add_argument("--out", help="출력 경로 (미지정 시 stdout)")
    args = parser.parse_args()

    if args.csv:
        if not args.column:
            parser.error("--csv 사용 시 --column 필요")
        label_csv_column(args.csv, args.column, args.configs, out_path=args.out)
        print(f"[done] {args.out or '(no --out; nothing saved)'}")
    else:
        text = args.text if args.text is not None else Path(args.in_file).read_text(encoding="utf-8")
        result = label_text(text, args.configs)
        if args.out:
            Path(args.out).write_text(result, encoding="utf-8")
            print(f"[done] {args.out}")
        else:
            sys.stdout.write(result + "\n")
