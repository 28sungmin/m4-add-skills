import ast
import time
import yaml
import argparse
import threading
import pandas as pd
import subprocess
import seaborn as sns
import matplotlib.pyplot as plt
from tqdm import tqdm
from matplotlib.axes import Axes


MAPPING_INFO_2 = {
    "ACT": "CT abdomen",
    "BCT": "CT brain",
    "CCT": "CT chest",
    "SCT": "CT spine",
    "CXR": "X-ray chest",
    "AXR": "X-ray abdomen",
    "SXR": "X-ray spine",
    "ECH": "Echocardiography",
    "ADM": "Admission note",
    "DIS": "Discharge summary",
    "SUR": "Surgery note",
    "EME": "Emergency note",
}

_SYSTEM_CLINICAL = """Please review the medical record provided and identify errors in the following specific categories:

1) Spelling or grammatical error
2) Diagnostic Information Errors:
- Incorrect or missing disease diagnosis (eg. DM type 1 -> DM type 2), inaccuracies in the anatomic locations mentioned (eg. ascending colon -> rectum), discrepancies in locations (eg. right -> left).
3) Drug Information Errors
- Incorrect or missing in prescribed drugs in report.
4) Procedure Information Errors:
- Incorrect or missing procedure names, inaccuracies in the anatomic locations mentioned, discrepancies in locations.
5) Demographic Information Errors:
- Incorrect or missing patient details such as name, age, or sex.
6) Date Information Errors
- Incorrect or missing dates, chronological errors.

Format your response exactly as follows (JSON):
- Spelling or Grammatical Errors: Yes/No (Brief Reason)
- Diagnostic Information Error: Yes/No (Brief Reason)
- Drug Information Error: Yes/No (Brief Reason)
- Procedure Information Error: Yes/No (Brief Reason)
- Demographic Information Error: Yes/No (Brief Reason)
- Date Information Error: Yes/No (Brief Reason)

Note:
-Limit your explanation for each error to fewer than 5 words.
-Only report errors that fall into these 6 specified categories.
-If multiple errors occur within a single category, number them.
-Medication instruction or treatment plan may change between admission and discharge, but the diagnosis and treatment names should remain the same.
"""

_SYSTEM_RADIOLOGY = """
Task:
Assess the "Impression" section of a radiology report for critical errors that may have significant clinical implications.

Output Format (JSON):
{
    "error 1": "{Specify the identified error clearly or state 'no error'}",
    "error 1 reason": "{Specify the reason of error if applicable, or state 'N/A'}"
}
"""


def draw_unstructured_accuracy_box_plot(ax: Axes, result_df: pd.DataFrame):
    ax.clear()
    filtered = result_df[result_df['Mapping_info_2'].isin(MAPPING_INFO_2)].copy()
    filtered['Mapping_info_2'] = filtered['Mapping_info_2'].map(MAPPING_INFO_2)
    sns.boxplot(x='Mapping_info_2', y='Accuracy_results', data=filtered, ax=ax)
    sns.stripplot(x='Mapping_info_2', y='Accuracy_results', data=filtered,
                  color='blue', jitter=True, alpha=0.5, size=10, ax=ax)
    ax.set_xlabel('Category', fontsize=12)
    ax.set_ylabel('Accuracy Results (%)', fontsize=12)
    ax.set_ylim(0, 100)
    unique_cats = filtered['Mapping_info_2'].unique()
    ax.set_xticks(range(len(unique_cats)))
    ax.set_xticklabels(unique_cats, rotation=30)
    ax.grid()


def _call_claude(system_content: str, note_text: str, timeout: int = 60) -> str | None:
    """Send one note to Claude CLI and return the response text (or None on failure)."""
    try:
        result = subprocess.run(
            ['claude', '-p', '<value note> ' + note_text, '--system-prompt', system_content],
            capture_output=True, text=True, timeout=timeout
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip()
    except Exception:
        return None


def _process_notes(df: pd.DataFrame, system_content: str, result_col: str) -> pd.DataFrame:
    """Run LLM over each row; retry failed rows once."""
    df = df.copy()
    df[result_col] = None
    errors_to_retry = []
    start = time.time()

    for i, row in tqdm(df.iterrows(), total=len(df), desc=f"Processing {result_col}"):
        text = _call_claude(system_content, str(row['Value']))
        if text is None:
            errors_to_retry.append(i)
        else:
            df.at[i, result_col] = text

    for i in errors_to_retry:
        print(f"Retry row {i}")
        text = _call_claude(system_content, str(df.at[i, 'Value']))
        if text is not None:
            df.at[i, result_col] = text

    print(f"Elapsed for {result_col}: {time.time() - start:.1f}s\n")
    return df


def _score_clinical(cell: str):
    """Return % of 'No' responses among Diagnostic + Procedure categories."""
    try:
        lines = cell.split('\n')
        targets = ['Diagnostic Information Error', 'Procedure Information Error']
        total, no_count = 0, 0
        for line in lines:
            for t in targets:
                if t in line:
                    total += 1
                    if 'No' in line:
                        no_count += 1
        return no_count / total * 100 if total > 0 else None
    except Exception:
        return None


def _score_radiology(cell: str):
    """Return 100 if no error found, 0 if error found, None on parse failure."""
    try:
        row_dict = ast.literal_eval(cell)
        if 'error 1' in row_dict:
            return 100 if row_dict['error 1'].lower() == 'no error' else 0
        return None
    except (ValueError, SyntaxError):
        return None


def _run_clinical(quiq: pd.DataFrame):
    df = quiq[quiq['Mapping_info_1'] == 'note_clinical'].copy()
    df = _process_notes(df, _SYSTEM_CLINICAL, 'Accuracy_clinical')
    df['Accuracy_clinical_result'] = df['Accuracy_clinical'].apply(_score_clinical)
    mean = df['Accuracy_clinical_result'].mean()
    std = df['Accuracy_clinical_result'].std()
    return df, mean, std


def _run_radiology(quiq: pd.DataFrame):
    df = quiq[quiq['Mapping_info_1'] == 'note_rad'].copy()
    df = _process_notes(df, _SYSTEM_RADIOLOGY, 'Accuracy_radiology')
    df['Accuracy_radiology_result'] = df['Accuracy_radiology'].apply(_score_radiology)
    mean = df['Accuracy_radiology_result'].mean()
    std = df['Accuracy_radiology_result'].std()
    return df, mean, std


def get_note_accuracy(quiq: pd.DataFrame):
    """
    Parameters
    ----------
    quiq : QUIQ-format DataFrame

    Returns
    -------
    df_clinical   : clinical note rows with LLM output + score
    df_radiology  : radiology note rows with LLM output + score
    result_df     : combined result with Accuracy_results column
    summary_df    : per-(Mapping_info_1, Mapping_info_2) summary
    """
    assert len(quiq[quiq['Mapping_info_1'].isin(['note_rad', 'note_clinical'])]) > 0, \
        'FAIL: No note_rad or note_clinical rows in QUIQ table.'

    df_clinical, _, _ = _run_clinical(quiq)
    df_radiology, _, _ = _run_radiology(quiq)

    df_c = df_clinical.rename(columns={
        'Accuracy_clinical': 'Accuracy',
        'Accuracy_clinical_result': 'Accuracy_results',
    })
    df_r = df_radiology.rename(columns={
        'Accuracy_radiology': 'Accuracy',
        'Accuracy_radiology_result': 'Accuracy_results',
    })

    result_df = pd.concat([df_c, df_r], ignore_index=True)
    result_df = result_df.dropna(subset=['Accuracy_results'])

    summary_df = (
        result_df
        .groupby(['Mapping_info_1', 'Mapping_info_2'])['Accuracy_results']
        .agg(
            Count='count',
            Accuracy_score_mean=lambda x: round(x.mean(), 2),
            Accuracy_score_std=lambda x: round(x.std(), 2),
        )
        .reset_index()
    )
    summary_df['Mapping_info_2_'] = summary_df['Mapping_info_2'].map(MAPPING_INFO_2)
    summary_df = summary_df[
        ['Mapping_info_1', 'Mapping_info_2', 'Mapping_info_2_', 'Count', 'Accuracy_score_mean', 'Accuracy_score_std']
    ].sort_values(by='Accuracy_score_mean', ascending=False)

    return df_clinical, df_radiology, result_df, summary_df


if __name__ == '__main__':
    print('<LYDUS - Note Accuracy>\n')

    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=str, required=True)
    args = parser.parse_args()

    with open(args.config, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    quiq = pd.read_csv(config['quiq_path'])
    save_path = config['save_path']

    df_clinical, df_radiology, result_df, summary_df = get_note_accuracy(quiq=quiq)

    detail_cols = [
        'Mapping_info_1', 'Mapping_info_2', 'Primary_key', 'Original_table_name',
        'Variable_name', 'Event_date', 'Value', 'Accuracy', 'Accuracy_results',
    ]
    result_df.to_csv(f"{save_path}/note_accuracy_total_detail.csv", index=False,
                     columns=[c for c in detail_cols if c in result_df.columns])
    summary_df.to_csv(f"{save_path}/note_accuracy_summary.csv", index=False)

    fig, ax = plt.subplots(figsize=(8, 5))
    draw_unstructured_accuracy_box_plot(ax, result_df)
    fig.tight_layout()
    fig.savefig(f"{save_path}/note_accuracy_plot.png")

    mean_accuracy = round(result_df['Accuracy_results'].mean(), 2)
    with open(f"{save_path}/note_accuracy_total.txt", 'w', encoding='utf-8') as f:
        f.write(f'Note Accuracy (%) = {mean_accuracy}\n')

    print('<SUCCESS>')
