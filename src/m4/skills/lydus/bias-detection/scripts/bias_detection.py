import gc
import os
import sys
import yaml
import argparse
import contextlib
import numpy as np
import pandas as pd
import subprocess

# ── Skill dependency imports ──────────────────────────────────────────────────
# Each sibling skill's scripts/ dir is added to sys.path so its module is
# importable by filename (e.g. completeness.py → `from completeness import ...`).
_SKILLS_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

for _dep in [
    'completeness', 'date-validity', 'classification', 'preciseness',
    'range-validity', 'format-validity', 'sequence-validity',
    'cross-sectional-consistency', 'time-series-consistency',
    'fidelity', 'note-fidelity', 'note-accuracy',
    'class-diversity', 'instance-diversity',
    'vocabulary-diversity', 'sentence-diversity', 'logical-accuracy',
]:
    _p = os.path.join(_SKILLS_ROOT, _dep, 'scripts')
    if _p not in sys.path:
        sys.path.insert(0, _p)

from completeness import get_completeness
from date_validity import get_date_validity
from classification import get_classification
from preciseness import get_preciseness
from range_validity import get_range_validity
from format_validity import get_code_validity
from sequence_validity import get_sequence_validity
from cross_sectional_consistency import get_cross_sectional_consistency
from time_series_consistency import get_time_series_consistency
from fidelity import get_structured_fidelity
from note_fidelity import get_note_fidelity
from note_accuracy import get_note_accuracy
from class_diversity import get_class_diversity
from instance_diversity import get_instance_diversity
from vocabulary_diversity import get_vocabulary_diversity
from sentence_diversity import get_sentence_diversity
from logical_accuracy import get_logical_accuracy


@contextlib.contextmanager
def _suppress():
    with open(os.devnull, 'w') as f:
        with contextlib.redirect_stdout(f), contextlib.redirect_stderr(f):
            yield


def _make_var_list_text(var_list) -> str:
    return ', '.join(str(v) for v in var_list)


def _call_claude(system_prompt: str, user_content: str, timeout: int = 60) -> str:
    result = subprocess.run(
        ['claude', '-p', user_content, '--system-prompt', system_prompt],
        capture_output=True, text=True, timeout=timeout
    )
    if result.returncode != 0:
        raise RuntimeError(f'Claude CLI error: {result.stderr}')
    return result.stdout.strip()


def _llm_ask_column(var_list_text: str, target_concept: str):
    """Ask Claude to pick the single variable most relevant to target_concept."""
    system_prompt = (
        f'You are a medical data expert.\n'
        f'A list of variable names will be provided.\n'
        f'From the provided variables, select exactly one variable that is most relevant to **{target_concept}**.\n'
        f'Respond with **only** the variable name, no additional explanation.\n'
        f'Return it **exactly as it appears** in the provided list.\n'
        f'If no appropriate variable is found, respond with \'None\'.'
    )
    result = _call_claude(system_prompt, f'List of variable names : {var_list_text}')
    return None if result == 'None' else result


def _run_all_metrics(g, quiq: pd.DataFrame, via: pd.DataFrame, config: dict) -> dict:
    """
    Run all LYDUS metrics on a group-filtered QUIQ DataFrame.
    Returns {(metric_name, g): score} for all metrics.
    Errors are caught per-metric and stored as np.nan.
    """
    scores = {}
    save_path = config.get('save_path', '.')

    # ── Range Validity ────────────────────────────────────────────────────────
    print('<Range Validity>', end=' ', flush=True)
    gc.collect()
    try:
        with _suppress():
            _, df_s, _ = get_range_validity(quiq)
        total = df_s['Total_num'].sum()
        outlier = df_s['Outlier_total_num'].sum()
        scores[('Range Validity', g)] = round((total - outlier) / total * 100, 2)
    except Exception as e:
        print(f'[ERR: {e}]', end=' ')
        scores[('Range Validity', g)] = np.nan

    # ── Date Validity ─────────────────────────────────────────────────────────
    print('<Date Validity>', end=' ', flush=True)
    gc.collect()
    try:
        with _suppress():
            _, df_s = get_date_validity(quiq)
        total = df_s['Total_date'].sum()
        invalid = df_s['Invalid_date'].sum()
        scores[('Date Validity', g)] = round((total - invalid) / total * 100, 2)
    except Exception as e:
        print(f'[ERR: {e}]', end=' ')
        scores[('Date Validity', g)] = np.nan

    # ── Format Validity ───────────────────────────────────────────────────────
    print('<Format Validity>', end=' ', flush=True)
    gc.collect()
    try:
        with _suppress():
            _, df_s = get_code_validity(quiq, via)
        total = df_s['Total_code'].sum()
        invalid = df_s['Invalid_code'].sum()
        scores[('Format Validity', g)] = round((total - invalid) / total * 100, 2)
    except Exception as e:
        print(f'[ERR: {e}]', end=' ')
        scores[('Format Validity', g)] = np.nan

    # ── Sequence Validity ─────────────────────────────────────────────────────
    print('<Sequence Validity>', end=' ', flush=True)
    gc.collect()
    try:
        with _suppress():
            _, df_s = get_sequence_validity(quiq)
        total = df_s['Total_num'].sum()
        invalid = df_s['Invalid_num'].sum()
        scores[('Sequence Validity', g)] = round((total - invalid) / total * 100, 2)
    except Exception as e:
        print(f'[ERR: {e}]', end=' ')
        scores[('Sequence Validity', g)] = np.nan

    # ── Completeness ──────────────────────────────────────────────────────────
    print('<Completeness>', end=' ', flush=True)
    gc.collect()
    try:
        with _suppress():
            df_s = get_completeness(quiq)
        total = df_s['Total_num'].sum()
        null = df_s['Null_num'].sum()
        scores[('Completeness', g)] = round((total - null) / total * 100, 2)
    except Exception as e:
        print(f'[ERR: {e}]', end=' ')
        scores[('Completeness', g)] = np.nan

    # ── Logical Accuracy ──────────────────────────────────────────────────────
    print('<Logical Accuracy>', end=' ', flush=True)
    gc.collect()
    try:
        with _suppress():
            var_list_target, dict_total, dict_outlier = get_logical_accuracy(
                quiq,
                config.get('operation_type_manual', False),
                config.get('target_variable', ''),
                config.get('automatic_num', 5),
                config.get('recommend_num', 5),
            )
        total = sum(len(dict_total[v]) for v in var_list_target)
        outlier = sum(len(dict_outlier[v]) for v in var_list_target)
        scores[('Logical Accuracy', g)] = round((total - outlier) / total * 100, 2)
    except Exception as e:
        print(f'[ERR: {e}]', end=' ')
        scores[('Logical Accuracy', g)] = np.nan

    # ── Cross-Sectional Consistency ───────────────────────────────────────────
    print('<Cross Sectional Consistency>', end=' ', flush=True)
    gc.collect()
    try:
        with _suppress():
            avg_consistency, _, _ = get_cross_sectional_consistency(quiq, via)
        scores[('Cross Sectional Consistency', g)] = round(avg_consistency * 100, 2)
    except Exception as e:
        print(f'[ERR: {e}]', end=' ')
        scores[('Cross Sectional Consistency', g)] = np.nan

    # ── Time Series Consistency ───────────────────────────────────────────────
    print('<Time Series Consistency>', end=' ', flush=True)
    gc.collect()
    try:
        with _suppress():
            # M4 skill arg order: (quiq, save_path) — original had them reversed
            _, df_s = get_time_series_consistency(quiq, save_path)
        valid = df_s.dropna(subset=['Total_time_point'])
        total_tp = valid['Total_time_point'].sum()
        change_pt = valid['Change_point'].sum()
        scores[('Time Series Consistency', g)] = round((total_tp - change_pt) / total_tp * 100, 2)
    except Exception as e:
        print(f'[ERR: {e}]', end=' ')
        scores[('Time Series Consistency', g)] = np.nan

    # ── Class Diversity ───────────────────────────────────────────────────────
    print('<Class Diversity>', end=' ', flush=True)
    gc.collect()
    try:
        with _suppress():
            df_s, _ = get_class_diversity(quiq)
        total = df_s['Total Number of Data'].sum()
        weighted = (df_s['Total Number of Data'] * df_s['Class_diversity (%)']).sum() / total
        scores[('Class Diversity', g)] = round(weighted, 2)
    except Exception as e:
        print(f'[ERR: {e}]', end=' ')
        scores[('Class Diversity', g)] = np.nan

    # ── Instance Diversity ────────────────────────────────────────────────────
    print('<Instance Diversity>', end=' ', flush=True)
    gc.collect()
    try:
        with _suppress():
            _, _, weighted_simpson = get_instance_diversity(quiq)
        scores[('Instance Diversity', g)] = weighted_simpson
    except Exception as e:
        print(f'[ERR: {e}]', end=' ')
        scores[('Instance Diversity', g)] = np.nan

    # ── Fidelity ──────────────────────────────────────────────────────────────
    print('<Fidelity>', end=' ', flush=True)
    gc.collect()
    try:
        with _suppress():
            df_s = get_structured_fidelity(quiq)
        total = df_s['Patient_num'].sum()
        weighted = (df_s['Patient_num'] * df_s['Mean']).sum() / total
        scores[('Fidelity', g)] = round(weighted, 2)
    except Exception as e:
        print(f'[ERR: {e}]', end=' ')
        scores[('Fidelity', g)] = np.nan

    # ── Preciseness ───────────────────────────────────────────────────────────
    print('<Preciseness>', end=' ', flush=True)
    gc.collect()
    try:
        with _suppress():
            df_s, _ = get_preciseness(quiq)
        total = df_s['Total_num'].sum()
        weighted = (df_s['Total_num'] * df_s['Preciseness (%)']).sum() / total
        scores[('Preciseness', g)] = round(weighted, 2)
    except Exception as e:
        print(f'[ERR: {e}]', end=' ')
        scores[('Preciseness', g)] = np.nan

    # ── Classification ────────────────────────────────────────────────────────
    print('<Classification>', end=' ', flush=True)
    gc.collect()
    try:
        with _suppress():
            _, _, (w_acc, w_prec, w_rec, w_f1, w_auc) = get_classification(quiq)
        scores[('Accuracy', g)] = w_acc
        scores[('Precision', g)] = w_prec
        scores[('Recall', g)] = w_rec
        scores[('F1score', g)] = w_f1
        scores[('AUROC', g)] = w_auc
    except Exception as e:
        print(f'[ERR: {e}]', end=' ')
        for m in ('Accuracy', 'Precision', 'Recall', 'F1score', 'AUROC'):
            scores[(m, g)] = np.nan

    # ── Note Fidelity ─────────────────────────────────────────────────────────
    print('<Note Fidelity>', end=' ', flush=True)
    gc.collect()
    try:
        with _suppress():
            # get_note_fidelity returns 8 values; we need result_df (index 2)
            _, _, result_df, *_ = get_note_fidelity(quiq)
        scores[('Note Fidelity', g)] = round(result_df['Fidelity_results'].mean(), 2)
    except Exception as e:
        print(f'[ERR: {e}]', end=' ')
        scores[('Note Fidelity', g)] = np.nan

    # ── Note Accuracy ─────────────────────────────────────────────────────────
    print('<Note Accuracy>', end=' ', flush=True)
    gc.collect()
    try:
        with _suppress():
            _, _, result_df, _ = get_note_accuracy(quiq)
        scores[('Note Accuracy', g)] = round(result_df['Accuracy_results'].mean(), 2)
    except Exception as e:
        print(f'[ERR: {e}]', end=' ')
        scores[('Note Accuracy', g)] = np.nan

    # ── Vocabulary Diversity ──────────────────────────────────────────────────
    print('<Vocabulary Diversity>', end=' ', flush=True)
    gc.collect()
    try:
        with _suppress():
            word_diversity, _, _, _ = get_vocabulary_diversity(quiq, top_n=10)
        scores[('Vocabulary Diversity', g)] = word_diversity
    except Exception as e:
        print(f'[ERR: {e}]', end=' ')
        scores[('Vocabulary Diversity', g)] = np.nan

    # ── Sentence Diversity ────────────────────────────────────────────────────
    print('<Sentence Diversity>', flush=True)
    gc.collect()
    try:
        with _suppress():
            sentence_diversity, _, _, _ = get_sentence_diversity(quiq, top_n=10)
        scores[('Sentence Diversity', g)] = sentence_diversity
    except Exception as e:
        print(f'[ERR: {e}]', end=' ')
        scores[('Sentence Diversity', g)] = np.nan

    return scores


def _build_results_df(group_scores_list: list) -> pd.DataFrame:
    """
    Combine per-group score dicts into a DataFrame.
    Rows = metrics, Columns = group labels + Mean + GDI.
    GDI = max |group_score − mean| across groups (Group Disparity Index).
    """
    combined = {}
    for d in group_scores_list:
        combined.update(d)

    df = pd.Series(combined).unstack()
    df['Mean'] = df.mean(axis=1)
    df['GDI'] = df.drop(columns='Mean').sub(df['Mean'], axis=0).abs().max(axis=1)
    return df


def get_bias_detection(
    quiq: pd.DataFrame,
    via: pd.DataFrame,
    config: dict,
) -> tuple:
    """
    Parameters
    ----------
    quiq   : QUIQ-format DataFrame
    via    : VIA (Variable Information Annotation) DataFrame
    config : dict with keys:
               model_ver, api_key, save_path,
               operation_type_manual, target_variable,
               automatic_num, recommend_num

    Returns
    -------
    df_sex_results   : DataFrame (metrics × sex groups + Mean + GDI)
    df_race_results  : DataFrame (metrics × race groups + Mean + GDI)
    df_age_results   : DataFrame (metrics × age groups + Mean + GDI)
    Empty DataFrames are returned when a grouping variable is not found.
    """
    # ── Identify demographic columns via LLM ─────────────────────────────────
    print('Identify demographic grouping variables')
    var_list = quiq['Variable_name'].unique().tolist()
    var_list_text = _make_var_list_text(var_list)

    sex_col = _llm_ask_column(var_list_text, 'biological sex')
    race_col = _llm_ask_column(var_list_text, 'race')
    birth_col = _llm_ask_column(var_list_text, 'date of birth')
    print(f'  Sex   → {sex_col}')
    print(f'  Race  → {race_col}')
    print(f'  Birth → {birth_col}')

    # ── Build per-patient demographics pivot ──────────────────────────────────
    print('Build demographics pivot')
    demo_cols = [c for c in [sex_col, race_col, birth_col] if c is not None]
    demo_df = quiq[quiq['Variable_name'].isin(demo_cols)]
    demo_pivot = (
        demo_df
        .pivot_table(index='Patient_id', columns='Variable_name', values='Value', aggfunc='first')
        .reset_index()
    )
    del demo_df
    gc.collect()

    rename_map = {}
    if sex_col:   rename_map[sex_col]   = 'Sex'
    if race_col:  rename_map[race_col]  = 'Race'
    if birth_col: rename_map[birth_col] = 'BirthDate'
    demo_pivot.rename(columns=rename_map, inplace=True)

    df_merged = pd.merge(quiq, demo_pivot, on='Patient_id', how='left')
    del demo_pivot
    gc.collect()

    # ── Age calculation ───────────────────────────────────────────────────────
    if 'BirthDate' in df_merged.columns:
        print('Calculate age groups')
        age_numeric = pd.to_numeric(df_merged['BirthDate'], errors='coerce')
        if age_numeric.notna().mean() > 0.5:
            # BirthDate column actually contains numeric age values (e.g. anchor_age)
            df_merged['Age_Value'] = age_numeric
        else:
            df_merged['BirthDate'] = pd.to_datetime(df_merged['BirthDate'], errors='coerce')
            df_merged['Event_date'] = pd.to_datetime(df_merged['Event_date'], errors='coerce')
            df_merged['Age_Value'] = (
                df_merged['Event_date'].dt.year - df_merged['BirthDate'].dt.year
                - (
                    (df_merged['Event_date'].dt.month < df_merged['BirthDate'].dt.month)
                    | (
                        (df_merged['Event_date'].dt.month == df_merged['BirthDate'].dt.month)
                        & (df_merged['Event_date'].dt.day < df_merged['BirthDate'].dt.day)
                    )
                )
            )
        df_merged['Age_Group'] = pd.cut(
            df_merged['Age_Value'],
            bins=[0, 10, 20, 30, 40, 50, 60, 70, 80, 120],
            labels=['0-9', '10-19', '20-29', '30-39', '40-49', '50-59', '60-69', '70-79', '80+'],
            right=False,
        )

    # Drop rows missing the grouping variable before iterating
    if 'Sex'       in df_merged.columns: df_merged = df_merged.dropna(subset=['Sex'])
    if 'Race'      in df_merged.columns: df_merged = df_merged.dropna(subset=['Race'])
    if 'Age_Group' in df_merged.columns: df_merged = df_merged.dropna(subset=['Age_Group'])

    def _run_groups(col, sort_labels=False):
        if col not in df_merged.columns:
            return pd.DataFrame()
        groups = sorted(df_merged[col].unique()) if sort_labels else df_merged[col].unique()
        scores_list = []
        for g in groups:
            print(f'\n{"="*10} {col} - {g} {"="*10}')
            gc.collect()
            subset = df_merged[df_merged[col] == g]
            scores_list.append(_run_all_metrics(g, subset, via, config))
        return _build_results_df(scores_list) if scores_list else pd.DataFrame()

    df_sex_results  = _run_groups('Sex')
    df_race_results = _run_groups('Race', sort_labels=True)
    df_age_results  = _run_groups('Age_Group', sort_labels=True)

    return df_sex_results, df_race_results, df_age_results


if __name__ == '__main__':
    print('<LYDUS - Bias Detection>\n')

    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=str, required=True)
    args = parser.parse_args()

    with open(args.config, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    quiq = pd.read_csv(config['quiq_path'])
    via = pd.read_csv(config['via_path'])
    save_path = config['save_path']

    run_config = {
        'save_path':            save_path,
        'operation_type_manual': config.get('operation_type_manual', False),
        'target_variable':      config.get('target_variable', ''),
        'automatic_num':        config.get('automatic_num', 5),
        'recommend_num':        config.get('recommend_num', 5),
    }

    df_sex, df_race, df_age = get_bias_detection(quiq, via, run_config)

    os.makedirs(save_path, exist_ok=True)
    if len(df_sex)  > 0: df_sex.to_csv(os.path.join(save_path, 'bias_sex_summary.csv'))
    if len(df_race) > 0: df_race.to_csv(os.path.join(save_path, 'bias_race_summary.csv'))
    if len(df_age)  > 0: df_age.to_csv(os.path.join(save_path, 'bias_age_summary.csv'))

    print('\n<SUCCESS>')
