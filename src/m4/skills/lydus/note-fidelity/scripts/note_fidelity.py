import re
import yaml
import argparse
import openai
import pandas as pd
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

_CLINICAL_MAPPING = {
    "ADM": "Hospitalization Record",
    "DIS": "Discharge Record",
    "SUR": "Surgical Record",
    "EME": "Emergency Treatment Record",
}

_CLINICAL_TEMPLATES = {
    "Hospitalization Record": (
        "Admission department:\nChief complaint:\nPresent illness:\n"
        "Past medical history:\nSocial & Family history:\nPhysical examination:\n"
        "Review of systems:\nDiagnosis:\nTreatment plan:"
    ),
    "Discharge Record": (
        "Admission department:\nDischarge department:\nDischarge reason:\nDiagnosis:\n"
        "Summary of progression:\nMedical prescription:\nSurgery or procedure:\n"
        "Treatment result:\nDischarge plan:\nDischarge form:"
    ),
    "Surgical Record": (
        "Preoperative diagnosis:\nPostoperative diagnosis:\nPreoperative procedure:\n"
        "Postoperative procedure:\nType of anesthesia:\nOperative findings:\nSurgical procedure:"
    ),
    "Emergency Treatment Record": (
        "Visit information:\nPast medical history:\nMedication history:\n"
        "Present illness:\nExamination findings:\nPresumptive diagnosis:\nTreatment plan:"
    ),
}

_RADIOLOGY_MAPPING = {k: v for k, v in MAPPING_INFO_2.items()
                      if k in {"ACT", "BCT", "CCT", "SCT", "CXR", "AXR", "SXR", "ECH"}}

_RADIOLOGY_TEMPLATES = {
    "CT abdomen": (
        "Liver :\nGallbladder :\nSpleen :\nPancreas :\nAdrenals :\nKidneys :\n"
        "Bowel :\nMesentery/Peritoneum :\nNodes :\nPelvis :\nBone windows :\n"
        "Vasculature :\nSoft Tissues :"
    ),
    "CT brain": (
        "Extra-axial spaces:\nVentricular system:\nBasal cisterns:\nCerebral parenchyma:\n"
        "Cerebellum:\nBrainstem:\nVascular system:\nParanasal sinuses and mastoid air cells:\n"
        "Visualized orbits:\nBone:"
    ),
    "CT chest": (
        "Pulmonary Parenchyma and Airways:\nPleural Space:\nHeart and Pericardium:\n"
        "Mediastinum and Hila:\nThoracic Vessels:\nOsseous Structures and Chest Wall:\n"
        "Upper Abdomen:\nAdditional findings:"
    ),
    "CT spine": (
        "Alignment :\nBones :\nIntervertebral Discs :\nSpinal canal :\nParaspinal soft tissues :\nOthers :"
    ),
    "X-ray chest": (
        "Lungs :\nHeart :\nMediastinum :\nPleural Spaces :\nOsseous Structures :"
    ),
    "X-ray abdomen": (
        "Bowel gas pattern :\nAbnormal calcifications :\nBones :\nOthers :"
    ),
    "X-ray spine": (
        "Alignment :\nVertebral bodies :\nIntervertebral spaces :\nSoft Tissues :\nOthers:"
    ),
    "Echocardiography": (
        "Left ventricle :\nLeft atrium :\nRight atrium :\nRight ventricle :\n"
        "Aortic valve :\nMitral valve :\nTricuspid valve :\nPulmonic valve :\n"
        "Pericardium :\nAorta :\nPulmonary artery :\nInferior vena cava and pulmonary veins :"
    ),
}

_SYSTEM_PROMPT = (
    "Input is the template and the corresponding medical record.\n"
    "Task: Look at the items in the report template and determine whether each item is present "
    "in the medical record. Then classify them as \"mentioned\" or \"not mentioned\".\n"
    "Output format\n- (Item from the template): mentioned/not mentioned"
)


def draw_unst_fidelity_box_plot(ax: Axes, result_df: pd.DataFrame):
    ax.clear()
    filtered = result_df[result_df['Mapping_info_2'].isin(MAPPING_INFO_2)].copy()
    filtered['Mapping_info_2'] = filtered['Mapping_info_2'].map(MAPPING_INFO_2)
    sns.boxplot(x='Mapping_info_2', y='Fidelity_results', data=filtered, ax=ax)
    sns.stripplot(x='Mapping_info_2', y='Fidelity_results', data=filtered,
                  color='blue', jitter=True, alpha=0.5, size=10, ax=ax)
    ax.set_xlabel('Category', fontsize=12)
    ax.set_ylabel('Fidelity Results (%)', fontsize=12)
    ax.set_ylim(0, 100)
    unique_cats = filtered['Mapping_info_2'].unique()
    ax.set_xticks(range(len(unique_cats)))
    ax.set_xticklabels(unique_cats, rotation=30)
    ax.grid()


def _call_with_retry(client, model: str, template: str, note_text: str, attempts: int = 3):
    """Send template + note to LLM, retry up to `attempts` times on failure."""
    query = template + "\n" + str(note_text)
    for _ in range(attempts):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": query},
                ],
                temperature=0,
            )
            return resp.choices[0].message.content
        except Exception:
            pass
    return "Failed after retries"


def _score_clinical(report_text: str) -> float:
    """% of template items marked 'mentioned' in clinical note LLM response."""
    if not report_text:
        return 0.0
    items = re.findall(r':\s*("[^"]+"|[^:\n]+)', report_text)
    total = len(items)
    if total == 0:
        return 0.0
    not_mentioned = sum('not mentioned' in item.lower() for item in items)
    return round((1 - not_mentioned / total) * 100, 2)


def _score_radiology(text: str) -> float:
    """% of template items marked 'mentioned' in radiology report LLM response."""
    if not text or text == 'Invalid mapping or template missing':
        return 0.0
    items = [line for line in text.lower().split('\n') if line.strip()]
    total = len(items)
    if total == 0:
        return 0.0
    not_mentioned = sum('not mentioned' in line for line in items)
    return round((1 - not_mentioned / total) * 100, 2)


def _run_clinical(quiq: pd.DataFrame, client, model: str):
    df = quiq[quiq['Mapping_info_1'] == 'note_clinical'].copy()

    def process_row(row):
        note_type = _CLINICAL_MAPPING.get(row['Mapping_info_2'], "")
        template = _CLINICAL_TEMPLATES.get(note_type, "")
        if not template:
            return "Invalid mapping or template missing"
        return _call_with_retry(client, model, template, row['Value'])

    tqdm.pandas(desc="Running fidelity (clinical)")
    df['Fidelity_clinical'] = df.progress_apply(process_row, axis=1)

    df_filtered = df[df['Fidelity_clinical'] != 'Invalid mapping or template missing'].copy()
    df_filtered['Fidelity_clinical_results'] = df_filtered['Fidelity_clinical'].apply(_score_clinical)

    mean = round(df_filtered['Fidelity_clinical_results'].mean(), 2)
    std = round(df_filtered['Fidelity_clinical_results'].std(), 2)
    return df_filtered, mean, std


def _run_radiology(quiq: pd.DataFrame, client, model: str):
    df = quiq[quiq['Mapping_info_1'] == 'note_rad'].copy()

    def process_row(row):
        note_type = _RADIOLOGY_MAPPING.get(row['Mapping_info_2'], "")
        template = _RADIOLOGY_TEMPLATES.get(note_type, "")
        if not template:
            return "Invalid mapping or template missing"
        return _call_with_retry(client, model, template, row['Value'])

    tqdm.pandas(desc="Running fidelity (radiology)")
    df['Fidelity_radiology'] = df.progress_apply(process_row, axis=1)

    df_filtered = df[df['Fidelity_radiology'] != 'Invalid mapping or template missing'].copy()
    df_filtered['Fidelity_radiology_results'] = df_filtered['Fidelity_radiology'].apply(_score_radiology)

    mean = round(df_filtered['Fidelity_radiology_results'].mean(), 2)
    std = round(df_filtered['Fidelity_radiology_results'].std(), 2)
    return df_filtered, mean, std


def get_note_fidelity(quiq: pd.DataFrame, model: str, api_key: str):
    """
    Parameters
    ----------
    quiq    : QUIQ-format DataFrame
    model   : OpenAI model name (e.g. 'gpt-4o-mini')
    api_key : OpenAI API key

    Returns
    -------
    df_clinical    : clinical note rows with LLM output + fidelity score
    df_radiology   : radiology note rows with LLM output + fidelity score
    result_df      : combined result with Fidelity_results column
    summary_df     : per-(Mapping_info_1, Mapping_info_2) summary
    mean_clinical  : mean fidelity for clinical notes
    std_clinical   : std fidelity for clinical notes
    mean_radiology : mean fidelity for radiology reports
    std_radiology  : std fidelity for radiology reports
    """
    assert len(quiq[quiq['Mapping_info_1'].isin(['note_rad', 'note_clinical'])]) > 0, \
        'FAIL: No note_rad or note_clinical rows in QUIQ table.'

    client = openai.OpenAI(api_key=api_key)

    df_clinical, mean_clinical, std_clinical = _run_clinical(quiq.copy(), client, model)
    df_radiology, mean_radiology, std_radiology = _run_radiology(quiq.copy(), client, model)

    df_c = df_clinical.rename(columns={
        'Fidelity_clinical': 'Fidelity',
        'Fidelity_clinical_results': 'Fidelity_results',
    })
    df_r = df_radiology.rename(columns={
        'Fidelity_radiology': 'Fidelity',
        'Fidelity_radiology_results': 'Fidelity_results',
    })
    result_df = pd.concat([df_c, df_r], ignore_index=True)

    summary_df = (
        result_df
        .groupby(['Mapping_info_1', 'Mapping_info_2'])['Fidelity_results']
        .agg(
            Count='count',
            Fidelity_score_mean=lambda x: round(x.mean(), 2),
            Fidelity_score_std=lambda x: round(x.std(), 2),
        )
        .reset_index()
    )
    summary_df['Mapping_info_2_'] = summary_df['Mapping_info_2'].map(MAPPING_INFO_2)
    summary_df = summary_df[
        ['Mapping_info_1', 'Mapping_info_2', 'Mapping_info_2_', 'Count', 'Fidelity_score_mean', 'Fidelity_score_std']
    ].sort_values(by='Fidelity_score_mean', ascending=False)

    return df_clinical, df_radiology, result_df, summary_df, mean_clinical, std_clinical, mean_radiology, std_radiology


if __name__ == '__main__':
    print('<LYDUS - Note Fidelity>\n')

    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=str, required=True)
    args = parser.parse_args()

    with open(args.config, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    quiq = pd.read_csv(config['quiq_path'])
    save_path = config['save_path']

    df_clinical, df_radiology, result_df, summary_df, \
    mean_clinical, std_clinical, mean_radiology, std_radiology = get_note_fidelity(
        quiq=quiq,
        model=config['model_ver'],
        api_key=config['api_key'],
    )

    detail_cols = [
        'Mapping_info_1', 'Mapping_info_2', 'Primary_key', 'Original_table_name',
        'Variable_name', 'Event_date', 'Value', 'Fidelity', 'Fidelity_results',
    ]
    result_df.to_csv(f"{save_path}/note_fidelity_total_detail.csv", index=False,
                     columns=[c for c in detail_cols if c in result_df.columns])
    summary_df.to_csv(f"{save_path}/note_fidelity_summary.csv", index=False)

    fig, ax = plt.subplots(figsize=(8, 5))
    draw_unst_fidelity_box_plot(ax, result_df)
    fig.tight_layout()
    fig.savefig(f"{save_path}/note_fidelity_plot.png")

    mean_fidelity = round(result_df['Fidelity_results'].mean(), 2)
    with open(f"{save_path}/note_fidelity_total.txt", 'w', encoding='utf-8') as f:
        f.write(f'Note Fidelity (%) = {mean_fidelity}\n')

    print('\n<SUCCESS>')
