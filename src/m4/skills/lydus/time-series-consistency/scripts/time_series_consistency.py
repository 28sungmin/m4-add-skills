import gc
import os
import yaml
import argparse
import numpy as np
import pandas as pd
import shap
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score


def draw_auroc_plot(save_path: str, category: str, results_df: pd.DataFrame):
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(results_df['Year'].to_numpy(), results_df['AUROC'].to_numpy())
    ax.axhline(y=0.8, color='gray', linestyle='--')
    change_points = results_df[results_df['Is_change_point'] == 1]
    ax.scatter(change_points['Year'].to_numpy(), change_points['AUROC'].to_numpy(),
               color='red', marker='o')
    ax.set_title(f'{category} - AUROC plot')
    ax.set_xlabel('Year')
    ax.set_ylabel('AUROC')
    ax.set_ylim(-0.1, 1)
    fig.tight_layout()
    fig.savefig(os.path.join(save_path, f'{category} - AUROC plot.png'), facecolor='white')
    plt.close(fig)


def _detect_change_points(category: str, save_path: str,
                           df_pivot: pd.DataFrame, df_years: pd.DataFrame) -> pd.DataFrame:
    """For each year, train GBClassifier on year-1 vs year and check AUROC ≥ 0.8."""
    for idx, row in df_years.iterrows():
        target_year = row['Year']
        print(f'\n  {target_year}', end=' ')

        prev_mask = df_pivot['Event_date'].dt.year == target_year - 1
        curr_mask = df_pivot['Event_date'].dt.year == target_year
        n_prev = prev_mask.sum()
        n_curr = curr_mask.sum()

        if n_prev + n_curr == 0:
            df_years.at[idx, 'AUROC'] = -0.1
            print('FAIL - No data', end=' ')
            continue

        if min(n_prev, n_curr) / (n_prev + n_curr) < 0.25:
            df_years.at[idx, 'AUROC'] = -0.1
            print('FAIL - Data imbalance', end=' ')
            continue

        temp = df_pivot[prev_mask | curr_mask].copy()
        temp['Label'] = np.where(temp['Event_date'].dt.year == target_year, 1, 0)

        X = temp.drop(columns=['Patient_id', 'Event_date', 'Year', 'Label'])
        y = temp['Label']

        if y.value_counts().min() < 2:
            df_years.at[idx, 'AUROC'] = -0.1
            print('FAIL - Not enough data', end=' ')
            continue

        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.5, stratify=y)
        model = GradientBoostingClassifier()
        model.fit(X_train, y_train)

        auroc = roc_auc_score(y_test, model.predict_proba(X_test)[:, 1])
        df_years.at[idx, 'AUROC'] = auroc

        if auroc >= 0.8:
            df_years.at[idx, 'Is_change_point'] = 1
            print('CHANGE POINT!', end=' ')
            explainer = shap.TreeExplainer(model)
            shap_values = explainer.shap_values(X_test)
            fig = plt.figure()
            shap.summary_plot(shap_values, X_test, plot_type='bar', show=False)
            fig.savefig(
                os.path.join(save_path, f'{category} ({target_year}) - SHAP Plot.png'),
                facecolor='white', bbox_inches='tight'
            )
            plt.close(fig)

        gc.collect()

    print()
    return df_years


def _build_pivot_and_years(df: pd.DataFrame, pivot_column: str) -> tuple:
    """Build binary presence pivot table and year range DataFrame."""
    df = df.copy()
    df['Dummy'] = df[pivot_column]
    pivot = df.pivot_table(
        index=['Patient_id', 'Event_date'],
        columns=pivot_column,
        values='Dummy',
        aggfunc=lambda x: 1,
        fill_value=0,
    ).reset_index()
    pivot['Year'] = pivot['Event_date'].dt.year

    min_year = pivot['Year'].min() + 1
    max_year = pivot['Year'].max() - 1
    years_df = pd.DataFrame({
        'Year': np.arange(min_year, max_year),
        'AUROC': np.nan,
        'Is_change_point': 0,
    })
    return pivot, years_df


def _run_category(label: str, df_filtered: pd.DataFrame,
                  pivot_column: str, save_path: str) -> pd.DataFrame | None:
    """Run change-point detection for one category; return results_df or None."""
    if len(df_filtered) == 0:
        print(f'\nFAIL - No data for {label}')
        return None

    pivot, years_df = _build_pivot_and_years(df_filtered, pivot_column)

    if len(years_df) == 0:
        print(f'FAIL - Not enough historical data for {label}.')
        return None

    return _detect_change_points(label, save_path, pivot, years_df)


def get_time_series_consistency(quiq: pd.DataFrame, save_path: str) -> tuple:
    """
    Parameters
    ----------
    quiq      : QUIQ-format DataFrame
    save_path : directory for AUROC + SHAP plots

    Returns
    -------
    total_results : dict with keys 'event', 'diagnosis', 'prescription', 'procedure'
    summary       : DataFrame with Category, Total_time_point, Change_point, Time Series Consistency (%)
    """
    df = quiq.copy()
    df['Event_date'] = pd.to_datetime(df['Event_date'], errors='coerce')
    df = df.dropna(subset=['Event_date'])
    df['Mapping_info_1'] = df['Mapping_info_1'].astype(str)
    df['Mapping_info_2'] = df['Mapping_info_2'].astype(str)

    categories = {
        'Event': (
            df[
                df['Mapping_info_1'].str.contains('event', case=False, na=False) &
                df['Mapping_info_2'].str.contains('lab_event', case=False, na=False)
            ],
            'Variable_name',
        ),
        'Diagnosis': (
            df[df['Mapping_info_1'].str.contains('diagnosis', case=False, na=False)],
            'Value',
        ),
        'Prescription': (
            # bug fix: original checked Mapping_info_1 for 'drug' (always empty);
            # correct filter is Mapping_info_2 contains 'drug'
            df[
                df['Mapping_info_1'].str.contains('prescription', case=False, na=False) &
                df['Mapping_info_2'].str.contains('drug', case=False, na=False)
            ],
            'Value',
        ),
        'Procedure': (
            df[df['Mapping_info_1'].str.contains('procedure', case=False, na=False)],
            'Value',
        ),
    }

    total_results = {}
    summary_rows = []

    for label, (df_cat, pivot_col) in categories.items():
        print(f'\nCATEGORY: {label}')
        results = _run_category(label, df_cat, pivot_col, save_path)

        if results is not None:
            total_results[label.lower()] = results
            total_tp = len(results)
            change_pt = int(results['Is_change_point'].sum())
            consistency = round((total_tp - change_pt) / total_tp * 100, 2)
        else:
            total_tp = np.nan
            change_pt = np.nan
            consistency = np.nan

        summary_rows.append({
            'Category': label,
            'Total_time_point': total_tp,
            'Change_point': change_pt,
            'Time Series Consistency (%)': consistency,
        })
        gc.collect()

    summary = pd.DataFrame(summary_rows)
    return total_results, summary


if __name__ == '__main__':
    print('<LYDUS - Time Series Consistency>\n')

    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=str, required=True)
    args = parser.parse_args()

    with open(args.config, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    quiq = pd.read_csv(config['quiq_path'])
    save_path = config['save_path']

    total_results, summary = get_time_series_consistency(quiq, save_path)

    valid = summary.dropna(subset=['Total_time_point'])
    total_tp = valid['Total_time_point'].sum()
    change_pt = valid['Change_point'].sum()
    consistency = round((total_tp - change_pt) / total_tp * 100, 2) if total_tp > 0 else np.nan

    with open(os.path.join(save_path, 'time_series_consistency_total.txt'), 'w', encoding='utf-8') as f:
        f.write(f'Time Series Consistency (%) = {consistency}\n')
        f.write(f'Total Time Points = {total_tp}\n')
        f.write(f'Change Points = {change_pt}\n')

    summary.to_csv(os.path.join(save_path, 'time_series_consistency_summary.csv'), index=False)

    for _, row in summary.iterrows():
        if not pd.isna(row['Time Series Consistency (%)']):
            category = row['Category'].lower()
            draw_auroc_plot(save_path, row['Category'], total_results[category])

    print('\n<SUCCESS>')
