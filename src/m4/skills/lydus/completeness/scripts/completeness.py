import yaml
import argparse
import numpy as np
import pandas as pd


def get_completeness(quiq: pd.DataFrame) -> pd.DataFrame:
    df = quiq.copy()

    non_null_counts = df.groupby(['Original_table_name', 'Variable_name'])['Value'].count()
    total_counts = df.groupby(['Original_table_name', 'Variable_name'])['Value'].size()
    completeness_ratio = np.round(non_null_counts.values / total_counts.values * 100, 2)

    completeness_df = pd.DataFrame({
        'Original_table_name': [idx[0] for idx in total_counts.index],
        'Variable_name': [idx[1] for idx in total_counts.index],
        'Total_num': total_counts.values,
        'Null_num': total_counts.values - non_null_counts.values,
        'Completeness (%)': completeness_ratio
    })

    return completeness_df


if __name__ == '__main__':
    print('<LYDUS - Completeness>\n')

    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=str, required=True)
    args = parser.parse_args()

    with open(args.config, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    quiq_path = config['quiq_path']
    save_path = config['save_path']

    quiq = pd.read_csv(quiq_path)
    df_summary = get_completeness(quiq)

    total_num = df_summary['Total_num'].sum()
    null_num = df_summary['Null_num'].sum()
    completeness = round((total_num - null_num) / total_num * 100, 2)

    with open(save_path + '/completeness_total.txt', 'w', encoding='utf-8') as f:
        f.write(f'Completeness (%) = {completeness}\n')
        f.write(f'Total Num = {total_num}\n')
        f.write(f'Null Num = {null_num}\n')

    df_summary.to_csv(save_path + '/completeness_summary.csv', index=False)

    print('\n<SUCCESS>')
