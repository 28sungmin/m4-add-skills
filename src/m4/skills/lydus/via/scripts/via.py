import os
import re
import sys
import subprocess
import yaml
import argparse
import pandas as pd


def read_document(doc_path: str) -> str:
    """Read PDF or plain-text document and return as string."""
    ext = os.path.splitext(doc_path)[1].lower()
    if ext == '.pdf':
        try:
            import pdfplumber
            with pdfplumber.open(doc_path) as pdf:
                pages = [page.extract_text() or '' for page in pdf.pages]
            return '\n'.join(pages)
        except ImportError:
            raise ImportError("PDF 읽기에 pdfplumber가 필요합니다: pip install pdfplumber")
    else:
        with open(doc_path, encoding='utf-8', errors='ignore') as f:
            return f.read()


def _ask_llm(system: str, user: str) -> str:
    """Call LLM via Anthropic SDK (if API key available) or claude CLI subprocess."""
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if api_key:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            msg = client.messages.create(
                model='claude-haiku-4-5-20251001',
                max_tokens=4096,
                system=system,
                messages=[{'role': 'user', 'content': user}],
            )
            return msg.content[0].text.strip()
        except Exception as e:
            print(f"  [SDK error] {e} — falling back to CLI")

    try:
        result = subprocess.run(
            ['claude', '-p', user, '--system-prompt', system],
            capture_output=True, text=True, timeout=300,
        )
        return result.stdout.strip() if result.returncode == 0 else ''
    except Exception as e:
        print(f"  [CLI error] {e}")
        return ''


def _describe_batch(batch: pd.DataFrame, system: str, user_prompt: str) -> list:
    """Send one batch to LLM and return list of descriptions."""
    response = _ask_llm(system, user_prompt)
    descriptions = []
    for line in response.splitlines():
        m = re.match(r'^\d+\.\s+(.*)', line.strip())
        if m:
            descriptions.append(m.group(1).strip())
    while len(descriptions) < len(batch):
        descriptions.append('')
    return descriptions


def _describe_event_variables(variables: pd.DataFrame) -> list:
    """
    For *EVENTS tables: Variable_name is a clinical measurement label (from d_items/d_labitems).
    LLM describes each label from medical knowledge — no document needed.
    """
    SYSTEM = (
        "You are a medical informatics expert. "
        "You will be given a list of clinical measurement labels from MIMIC-IV event tables "
        "(e.g., CHARTEVENTS, LABEVENTS, INPUTEVENTS). "
        "For each label, write a concise 1-2 sentence clinical description based on your medical knowledge. "
        "Output ONLY a numbered list in this exact format:\n"
        "1. <description for label 1>\n"
        "2. <description for label 2>\n"
        "No headers, no extra text, just the numbered list."
    )

    BATCH = 30
    rows = []
    total = len(variables)

    for start in range(0, total, BATCH):
        batch = variables.iloc[start:start + BATCH]
        end = min(start + BATCH, total)
        print(f"  [EVENTS {start + 1}–{end} / {total}] Describing from medical knowledge ...")

        var_list = '\n'.join(
            f"{i + 1}. Table: {row.Original_table_name} | Label: {row.Variable_name}"
            for i, row in enumerate(batch.itertuples())
        )
        descriptions = _describe_batch(batch, SYSTEM, var_list)

        for (_, var_row), desc in zip(batch.iterrows(), descriptions):
            rows.append({
                'Original_table_name': var_row['Original_table_name'],
                'Variable_name':       var_row['Variable_name'],
                'Description':         desc if desc else f"Clinical measurement: {var_row['Variable_name']}",
            })

    return rows


def _describe_schema_variables(variables: pd.DataFrame, doc_text: str) -> list:
    """
    For non-EVENTS tables: Variable_name is a column name.
    LLM finds descriptions from documentation; fallback to medical knowledge for any missing.
    """
    SYSTEM_DOC = (
        "You are a medical data annotation expert. "
        "You will be given a documentation text and a list of (table, column) pairs from MIMIC-IV. "
        "For each pair, find the column description in the documentation and write a concise 1-2 sentence description. "
        "If the documentation does not mention the column, write exactly: 'NO_DESC' "
        "Output ONLY a numbered list in this exact format:\n"
        "1. <description for variable 1>\n"
        "2. <description for variable 2>\n"
        "No headers, no extra text, just the numbered list."
    )

    SYSTEM_KNOWLEDGE = (
        "You are a medical informatics expert. "
        "You will be given a list of (table, column) pairs from MIMIC-IV clinical database. "
        "For each pair, write a concise 1-2 sentence description based on your medical knowledge. "
        "Output ONLY a numbered list in this exact format:\n"
        "1. <description for variable 1>\n"
        "2. <description for variable 2>\n"
        "No headers, no extra text, just the numbered list."
    )

    BATCH = 30
    rows = []
    total = len(variables)

    for start in range(0, total, BATCH):
        batch = variables.iloc[start:start + BATCH]
        end = min(start + BATCH, total)
        print(f"  [SCHEMA {start + 1}–{end} / {total}] Describing from documentation ...")

        var_list = '\n'.join(
            f"{i + 1}. Table: {row.Original_table_name} | Column: {row.Variable_name}"
            for i, row in enumerate(batch.itertuples())
        )
        user_prompt = f"=== DOCUMENTATION ===\n{doc_text}\n\n=== COLUMNS TO DESCRIBE ===\n{var_list}"
        descriptions = _describe_batch(batch, SYSTEM_DOC, user_prompt)

        # collect items that need fallback
        fallback_indices = []
        fallback_rows = []
        for i, ((_, var_row), desc) in enumerate(zip(batch.iterrows(), descriptions)):
            if not desc or desc.strip().upper().startswith('NO_DESC'):
                fallback_indices.append(i)
                fallback_rows.append(var_row)

        # fallback: describe missing variables from medical knowledge
        if fallback_rows:
            print(f"    → {len(fallback_rows)} missing → fallback to medical knowledge ...")
            fallback_df = pd.DataFrame(fallback_rows)
            fb_var_list = '\n'.join(
                f"{i + 1}. Table: {row['Original_table_name']} | Column: {row['Variable_name']}"
                for i, row in enumerate(fallback_rows)
            )
            fb_descs = _describe_batch(fallback_df, SYSTEM_KNOWLEDGE, fb_var_list)
            for idx, fb_desc in zip(fallback_indices, fb_descs):
                descriptions[idx] = fb_desc if fb_desc else f"Column {fallback_rows[fallback_indices.index(idx)]['Variable_name']} in MIMIC-IV {fallback_rows[fallback_indices.index(idx)]['Original_table_name']} table."

        for (_, var_row), desc in zip(batch.iterrows(), descriptions):
            rows.append({
                'Original_table_name': var_row['Original_table_name'],
                'Variable_name':       var_row['Variable_name'],
                'Description':         desc,
            })

    return rows


def get_via(quiq: pd.DataFrame, doc_path: str) -> pd.DataFrame:
    """
    Generate VIA table with two strategies:
    - Tables ending with 'EVENTS': Variable_name is a clinical label → LLM describes from medical knowledge
    - Other tables: Variable_name is a column name → LLM finds description in doc_path

    Parameters
    ----------
    quiq     : QUIQ-format DataFrame
    doc_path : Path to schema documentation file (PDF or text). Required for non-EVENTS tables.

    Returns
    -------
    pd.DataFrame with columns: Original_table_name, Variable_name, Description
    """
    if not doc_path or not os.path.exists(doc_path):
        print("\n⚠️  VIA 생성을 위한 변수 설명 문서가 필요합니다.")
        print("   데이터 딕셔너리 또는 컬럼 설명 문서(PDF, txt, md 등)의 경로를 제공해주세요.\n")
        sys.exit(1)

    print(f"Reading document: {doc_path}")
    doc_text = read_document(doc_path)
    print(f"Document length: {len(doc_text):,} characters\n")

    variables = (
        quiq[['Original_table_name', 'Variable_name']]
        .drop_duplicates()
        .sort_values(['Original_table_name', 'Variable_name'])
        .reset_index(drop=True)
    )

    is_event = variables['Original_table_name'].str.upper().str.endswith('EVENTS')
    event_vars  = variables[is_event].reset_index(drop=True)
    schema_vars = variables[~is_event].reset_index(drop=True)

    print(f"Total variables : {len(variables)}")
    print(f"  EVENTS tables : {len(event_vars)} vars → LLM (medical knowledge)")
    print(f"  Schema tables : {len(schema_vars)} vars → documentation\n")

    rows = []

    if len(event_vars) > 0:
        print("[Step 1] Describing EVENTS variables from medical knowledge...")
        rows.extend(_describe_event_variables(event_vars))
        print()

    if len(schema_vars) > 0:
        print("[Step 2] Describing schema variables from documentation...")
        rows.extend(_describe_schema_variables(schema_vars, doc_text))
        print()

    result = pd.DataFrame(rows, columns=['Original_table_name', 'Variable_name', 'Description'])
    return result.sort_values(['Original_table_name', 'Variable_name']).reset_index(drop=True)


if __name__ == '__main__':
    print('<LYDUS - VIA (Variable Information Archive)>\n')

    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=str, required=True)
    args = parser.parse_args()

    with open(args.config, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    quiq_path = config.get('quiq_path')
    doc_path  = config.get('doc_path')
    save_path = config['save_path']

    if not doc_path:
        print("\n⚠️  VIA 생성을 위한 변수 설명 문서가 필요합니다.")
        print("   config.yaml의 doc_path에 문서 경로를 지정해주세요.")
        print("   지원 형식: PDF (.pdf), 텍스트 (.txt, .md, .csv 등)\n")
        sys.exit(1)

    quiq = pd.read_csv(quiq_path)
    os.makedirs(save_path, exist_ok=True)

    via_df = get_via(quiq, doc_path)

    output_path = os.path.join(save_path, 'via.csv')
    via_df.to_csv(output_path, index=False, encoding='utf-8-sig')

    print(f'Saved {len(via_df):,} rows → {output_path}')
    print('<SUCCESS>')
