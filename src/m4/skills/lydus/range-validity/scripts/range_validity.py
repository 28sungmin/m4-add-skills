import os
import re
import yaml
import argparse
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.axes import Axes


def draw_range_validity_box_plot(fig, label: str, values: list):
    fig.clear()
    flierprops = dict(marker='o', markerfacecolor='green', markersize=2,
                      linestyle='none', alpha=0.2)
    ax = fig.add_subplot(111)
    if len(values) == 0:
        ax.set_title(f"{label}\n(No data)", fontsize=14, color="gray")
        ax.set_xticks([])
        ax.set_yticks([])
    else:
        ax.boxplot(values, flierprops=flierprops)
        ax.set_title(label, fontsize=10, fontweight='bold')
    fig.set_tight_layout(True)


def _get_outlier(series: pd.Series, weight: float = 1.5):
    q25 = np.percentile(series.values, 25)
    q75 = np.percentile(series.values, 75)
    iqr = q75 - q25
    lowest = q25 - weight * iqr
    highest = q75 + weight * iqr
    idx_under = series[series < lowest].index
    idx_upper = series[series > highest].index
    return q25, q75, lowest, highest, idx_under, idx_upper


def get_range_validity(quiq: pd.DataFrame, weight: float = 1.5):
    """
    Parameters
    ----------
    quiq   : QUIQ-format DataFrame
    weight : IQR multiplier for outlier bounds (default 1.5)

    Returns
    -------
    outlier_df    : all outlier rows with Direction ('under'/'upper')
    summary_df    : per-(table, variable) IQR stats and Range Validity (%)
    label_vs_boxplot : dict mapping 'TABLE - variable' → list of float values
    """
    df = quiq.copy()
    df['Variable_type'] = df['Variable_type'].astype(str)
    df['Is_categorical'] = pd.to_numeric(df['Is_categorical'], errors='coerce')

    df = df[df['Variable_type'].str.contains('numeric', case=False, na=False)]
    df = df[df['Is_categorical'] == 0]
    df['Value'] = pd.to_numeric(df['Value'], errors='coerce')
    df = df.dropna(subset=['Value']).reset_index(drop=True)

    filtered = df.groupby('Variable_name').filter(lambda x: len(x) > 1000)
    assert len(filtered) > 0, 'FAIL: No variables with more than 1000 data items.'

    labellist = (
        filtered.groupby(['Original_table_name', 'Variable_name'])
        .size()
        .sort_values(ascending=False)
        .index
        .tolist()
    )

    outlier_rows = []
    summary_rows = []
    label_vs_boxplot = {}
    error_list = []

    for table_name, var_name in labellist:
        # IQR computed on all rows for this Variable_name (pooled across tables)
        pool = df[df['Variable_name'] == var_name][['Patient_id', 'Value', 'Event_date']].copy()
        pool = pool.dropna(subset=['Value']).reset_index(drop=True)
        pool['Value'] = pool['Value'].astype(float)
        total = len(pool)

        identifier = f'{table_name} - {var_name}'
        label_vs_boxplot[identifier] = pool['Value'].tolist()

        try:
            _, _, _, _, idx_under, idx_upper = _get_outlier(pool['Value'], weight=weight)

            for direction, idx in [('under', idx_under), ('upper', idx_upper)]:
                rows = pool.loc[idx].copy()
                rows['Original_table_name'] = table_name
                rows['Variable_name'] = var_name
                rows['Direction'] = direction
                outlier_rows.append(
                    rows[['Original_table_name', 'Variable_name', 'Patient_id', 'Event_date', 'Value', 'Direction']]
                )

            n_under = len(idx_under)
            n_upper = len(idx_upper)
            n_total = n_under + n_upper

            summary_rows.append({
                'Original_table_name': table_name,
                'Variable_name': var_name,
                'Total_num': total,
                'Outlier_under_num': n_under,
                'Outlier_upper_num': n_upper,
                'Outlier_total_num': n_total,
                'Outlier_under_proportion': round(n_under / total, 3),
                'Outlier_upper_proportion': round(n_upper / total, 3),
                'Outlier_total_proportion': round(n_total / total, 3),
                'Range Validity (%)': round((total - n_total) / total * 100, 2),
            })
            print(f'{var_name} | under: {n_under}  upper: {n_upper}  total: {n_total}')

        except Exception as e:
            error_list.append((var_name, str(e)))

    outlier_df = pd.concat(outlier_rows, ignore_index=True) if outlier_rows else pd.DataFrame(
        columns=['Original_table_name', 'Variable_name', 'Patient_id', 'Event_date', 'Value', 'Direction']
    )
    summary_df = pd.DataFrame(summary_rows)

    return outlier_df, summary_df, label_vs_boxplot


if __name__ == '__main__':
    print('<LYDUS - Range Validity>\n')

    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=str, required=True)
    args = parser.parse_args()

    with open(args.config, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    quiq = pd.read_csv(config['quiq_path'], low_memory=False)
    save_path = config['save_path']
    weight = config.get('weight', 1.5)

    outlier_df, summary_df, label_vs_boxplot = get_range_validity(quiq, weight=weight)

    print('\nSave Results...')
    total_num = summary_df['Total_num'].sum()
    outlier_num = summary_df['Outlier_total_num'].sum()
    range_validity = round((total_num - outlier_num) / total_num * 100, 2)

    with open(os.path.join(save_path, 'range_validity_total.txt'), 'w', encoding='utf-8') as f:
        f.write(f'Range Validity (%) = {range_validity}\n')
        f.write(f'Total Num = {total_num}\n')
        f.write(f'Outlier Num = {outlier_num}\n')

    summary_df.to_csv(os.path.join(save_path, 'range_validity_summary.csv'), index=False)
    outlier_df.to_csv(os.path.join(save_path, 'range_validity_outlier_total.csv'), index=False)

    box_dir = os.path.join(save_path, 'range_validity_boxplots')
    os.makedirs(box_dir, exist_ok=True)

    identifiers = summary_df['Original_table_name'] + ' - ' + summary_df['Variable_name']
    for idx, identifier in enumerate(identifiers):
        fig = plt.figure(figsize=(3, 6))
        draw_range_validity_box_plot(fig, identifier, label_vs_boxplot[identifier])
        table_name, var_name = identifier.split(' - ', 1)
        table_name = re.sub(r'[\\/:*?"<>|]', ' ', table_name)
        var_name = re.sub(r'[\\/:*?"<>|]', ' ', var_name)
        fig.savefig(os.path.join(box_dir, f'{idx}_{table_name}_{var_name}.png'))
        plt.close(fig)

    print('\n<SUCCESS>')
