import gc
import os
import re
import yaml
import argparse
import pandas as pd
import subprocess


REGEX_CACHE = {
    'ICD-9':     r'^[0-9]{3}(\.[0-9]{1,2})?$',
    'ICD-10':    r'^[A-Z]{1}[0-9]{2}(\.[0-9]{1,2})?$',
    'ICD-11':    r'^[A-Z0-9]{1}[A-Z]{1}[0-9]{1}[A-Z0-9]{1}(\.[A-Z0-9]{1,2})?$',
    'SNOMED-CT': r'^[0-9]{6,18}$',
    'RxNorm':    r'^[0-9]{5,9}$',
    'LOINC':     r'^[0-9]{1,6}\-[0-9]{1}$',
    'ATC':       r'^[A-Z]{1}[0-9]{2}[A-Z]{2}[0-9]{2}$',
}


def match_code_regex(target_name: str, target_desc: str):
    """Rule-based code type detection from variable name and description."""
    name = target_name.lower()
    desc = target_desc.lower()

    if ('icd' in name and '9' in name) or ('icd' in desc and '9' in desc):
        code_name = 'ICD-9'
    elif ('icd' in name and '10' in name) or ('icd' in desc and '10' in desc):
        code_name = 'ICD-10'
    elif ('icd' in name and '11' in name) or ('icd' in desc and '11' in desc):
        code_name = 'ICD-11'
    elif ('snomed' in name and 'ct' in name) or ('snomed' in desc and 'ct' in desc):
        code_name = 'SNOMED-CT'
    elif 'rxnorm' in name or 'rxnorm' in desc:
        code_name = 'RxNorm'
    elif 'loinc' in name or 'loinc' in desc:
        code_name = 'LOINC'
    elif 'atc' in name or 'atc' in desc:
        code_name = 'ATC'
    else:
        return None, None

    return code_name, REGEX_CACHE[code_name]


def _llm_call(system_prompt: str, user_prompt: str) -> str:
    """Call LLM via Anthropic SDK (preferred) or claude CLI subprocess (fallback)."""
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if api_key:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            msg = client.messages.create(
                model='claude-haiku-4-5-20251001',
                max_tokens=256,
                system=system_prompt,
                messages=[{'role': 'user', 'content': user_prompt}],
            )
            return msg.content[0].text.strip()
        except Exception as e:
            print(f"  [SDK error] {e} — falling back to CLI")

    result = subprocess.run(
        ['claude', '-p', user_prompt, '--system-prompt', system_prompt],
        capture_output=True, text=True, timeout=120,
    )
    return result.stdout.strip() if result.returncode == 0 else 'None'


def _extract_regex(text: str) -> str:
    """Extract the first valid regex pattern from an LLM response."""
    # 코드블록 안의 패턴 우선 추출 (```...``` 또는 `...`)
    code_block = re.search(r'```[^\n]*\n?(.*?)```', text, re.DOTALL)
    if code_block:
        candidate = code_block.group(1).strip().splitlines()[0].strip()
        if candidate:
            return candidate

    # ^ 로 시작하는 첫 번째 줄 추출
    for line in text.splitlines():
        line = line.strip().strip('`').strip()
        if line.startswith('^'):
            return line

    # 백틱으로 감싸진 패턴
    backtick = re.search(r'`([^`]+)`', text)
    if backtick:
        return backtick.group(1).strip()

    return text.strip()


def _extract_code_name(text: str) -> str:
    """Extract a clean code name from an LLM response (strip markdown)."""
    # 마크다운 bold/italic 제거
    text = re.sub(r'\*+', '', text)
    # 괄호 설명 제거
    text = re.sub(r'\(.*?\)', '', text)
    # 첫 번째 비어있지 않은 줄의 첫 단어
    for line in text.splitlines():
        line = line.strip().strip('`').strip()
        if line and line.lower() != 'none':
            return line.split()[0]
    return 'None'


def llm_define_regex(target_name: str, target_description: str):
    """LLM fallback: identify code type and generate regex for unknown variables."""
    system_prompt_1 = (
        "You are a medical coding assistant.\n"
        "You will be given a name and a description of a variable.\n"
        "Your task is to identify and return **exactly one standardized medical code category** "
        "(e.g. ICD-9, SNOMED-CT) that best corresponds to the description of a variable.\n"
        "Respond with only the name of the code category, no additional explanation.\n"
        "If the description does not clearly correspond to any known code category, respond with 'None'"
    )
    raw_code = _llm_call(system_prompt_1,
                         f"Name of a variable : {target_name}\nDescription of a variable : {target_description}")
    code_name = _extract_code_name(raw_code)
    if not code_name or code_name.lower() == 'none':
        return None, None

    system_prompt_2 = (
        "You are a medical coding expert.\n"
        "You will be given the name of a standardized medical code category (e.g. ICD-9, SNOMED-CT).\n"
        "Your task is to return a SINGLE regular expression that captures the typical format of codes "
        "in that category.\n"
        "Rules:\n"
        "- Output ONLY the regex pattern, starting with ^ and ending with $\n"
        "- No explanation, no markdown, no code block, no extra text\n"
        "- If the format cannot be generalized, respond with the word: None"
    )
    raw_regex = _llm_call(system_prompt_2, f"Medical code category : {code_name}")
    if not raw_regex or raw_regex.strip().lower() == 'none':
        return code_name, None

    regex_for_target = _extract_regex(raw_regex)

    # 유효한 regex인지 검증
    try:
        re.compile(regex_for_target)
    except re.PatternError:
        print(f"  [WARN] Invalid regex from LLM for '{code_name}': {regex_for_target!r}")
        return code_name, None

    return code_name, regex_for_target


def get_code_validity(quiq: pd.DataFrame, via: pd.DataFrame, use_llm: bool = True):
    """
    Parameters
    ----------
    quiq    : QUIQ-format DataFrame
    via     : Variable Information Annotation — columns: Original_table_name, Variable_name, Description
    use_llm : If True (default), uses Claude CLI for unknown code type detection.
    """
    client = True if use_llm else None  # used only as boolean flag below

    quiq_df = quiq.copy()
    via_df = via.copy()
    quiq_df['Mapping_info_1'] = quiq_df['Mapping_info_1'].astype(str)

    filtered = quiq_df[quiq_df['Mapping_info_1'].str.contains('medical_code', case=False, na=False)]
    filtered = filtered.dropna(subset=['Value']).copy()
    filtered['Value'] = filtered['Value'].apply(
        lambda x: str(int(x)) if (isinstance(x, float) and x.is_integer()) else str(x)
    )
    filtered = filtered[['Original_table_name', 'Variable_name', 'Value']]

    assert len(filtered) > 0, 'FAIL : No value related to medical code'

    filtered['Identifier'] = filtered['Original_table_name'] + ' - ' + filtered['Variable_name']
    via_df['Identifier'] = via_df['Original_table_name'] + ' - ' + via_df['Variable_name']

    validation_parts = []

    for current_identifier in filtered['Identifier'].unique():
        target = filtered[filtered['Identifier'] == current_identifier].copy()
        target['Regex'] = ''
        target['Is_valid'] = False

        via_row = via_df[via_df['Identifier'] == current_identifier]
        if len(via_row) == 0:
            print(f"FAIL - '{current_identifier}' not found in VIA table.")
            validation_parts.append(target)
            continue

        name = via_row['Variable_name'].iloc[0]
        desc = via_row['Description'].iloc[0] if 'Description' in via_row.columns else ''
        code_name, regex = match_code_regex(str(name), str(desc))

        if regex is None and client is not None:
            code_name, regex = llm_define_regex(str(name), str(desc))

        if regex is None:
            if code_name is None:
                print(f"FAIL - Unable to identify code type for '{current_identifier}'")
            else:
                print(f"FAIL - Code type '{code_name}' detected but regex could not be defined for '{current_identifier}'")
            validation_parts.append(target)
            gc.collect()
            continue

        print(f"SUCCESS - '{code_name}' identified for '{current_identifier}' | regex: {regex}")
        target['Regex'] = regex
        target['Is_valid'] = target['Value'].str.match(regex)
        validation_parts.append(target)
        gc.collect()

    validation_df = pd.concat(validation_parts, axis=0) if validation_parts else pd.DataFrame(
        columns=['Original_table_name', 'Variable_name', 'Value', 'Regex', 'Is_valid', 'Identifier']
    )

    error_summary = validation_df.groupby(['Original_table_name', 'Variable_name']).agg(
        Total_code=('Value', 'count'),
        Valid_code=('Is_valid', 'sum'),
        Regular_Expression=('Regex', 'first')
    ).reset_index()
    error_summary['Format_Validity (%)'] = (error_summary['Valid_code'] / error_summary['Total_code'] * 100).round(2)
    error_summary['Invalid_code'] = error_summary['Total_code'] - error_summary['Valid_code']
    error_summary = error_summary.drop(columns=['Valid_code'])

    validation_df = validation_df[['Original_table_name', 'Variable_name', 'Value', 'Is_valid']]

    return validation_df, error_summary


if __name__ == '__main__':
    print('<LYDUS - Format Validity>\n')

    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=str, required=True)
    args = parser.parse_args()

    with open(args.config, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    quiq = pd.read_csv(config['quiq_path'])
    via = pd.read_csv(config['via_path'])
    save_path = config['save_path']
    use_llm = config.get('use_llm', True)

    validation_df, error_summary = get_code_validity(quiq, via, use_llm=use_llm)

    error_summary.to_csv(save_path + '/format_validity_summary.csv', index=False)
    validation_df.to_csv(save_path + '/format_validity_detail.csv', index=False)

    total_code = error_summary['Total_code'].sum()
    invalid_code = error_summary['Invalid_code'].sum()
    format_validity = round((total_code - invalid_code) / total_code * 100, 2)

    with open(save_path + '/format_validity_total.txt', 'w', encoding='utf-8') as f:
        f.write(f'Format Validity (%) = {format_validity}\n')
        f.write(f'Total Code = {total_code}\n')
        f.write(f'Invalid Code = {invalid_code}\n')

    print('<SUCCESS>')
