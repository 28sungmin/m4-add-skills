import os
import re
import math
import yaml
import argparse
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from decimal import Decimal
from collections import Counter


def draw_histogram(save_path: str, idx: int, identifier: str, hist_values: list):
    table_name, variable_name = identifier.split(' - ', 1)
    table_name = re.sub(r'[\\/:*?"<>|]', ' ', table_name)
    variable_name = re.sub(r'[\\/:*?"<>|]', ' ', variable_name)
    plt.title(identifier)
    plt.hist(hist_values)
    plt.savefig(os.path.join(save_path, 'preciseness_histograms', f'{idx}_{table_name}_{variable_name}.png'))
    plt.close()


def _gini_simpson(data: list) -> tuple:
    """Return (Gini-Simpson index %, diversity ratio) for a list of values."""
    total = len(data)
    counter = Counter(data)
    gini = 1.0 - sum((c / total) ** 2 for c in counter.values())
    diversity = round(len(counter) / total, 3)
    return round(gini * 100, 2), diversity


def _round_at_3(x) -> Decimal:
    return Decimal(str(x)).quantize(Decimal('0.001'))


def _multiply_by(x: Decimal, exp: int) -> Decimal:
    return x * (Decimal(10) ** exp)


def _detect_decimal_scale(values: pd.Series) -> tuple:
    """
    Detect the actual decimal precision of a numeric variable.

    Iterates multipliers from ×1000 down to ×0.1 (exp = 3..−1).
    Stops when <99% of values are divisible by 10 at that scale.

    Returns (decimalnum, last_digit_list, final_exp).
    - decimalnum: detected decimal places (−4 if all scales pass, i.e., data is very coarse)
    - last_digit_list: list of last digits (int) at the detected scale
    - final_exp: the exponent used (3 − iterr)
    """
    decimalnum = -4
    final_iterr = 4

    for iterr in range(5):
        exp = 3 - iterr
        scaled = values.apply(_multiply_by, args=(exp,))
        divisible = sum(
            math.isclose(float(v % 10), 0, abs_tol=0.001) or
            math.isclose(float(-v % 10), 0, abs_tol=0.001)
            for v in scaled
        )
        if divisible / len(scaled) <= 0.99:
            decimalnum = exp
            final_iterr = iterr
            break
        final_iterr = iterr

    final_exp = 3 - final_iterr
    scaled_final = values.apply(_multiply_by, args=(final_exp,))
    last_digits = [int(v % 10) for v in scaled_final]

    return decimalnum, last_digits


def get_preciseness(quiq: pd.DataFrame) -> tuple:
    """
    Parameters
    ----------
    quiq : QUIQ-format DataFrame

    Returns
    -------
    summary_df       : per-variable DataFrame with Total_num, Decimal_num, Preciseness (%)
    histogram_values : dict mapping 'TABLE - variable' → list of last-digit ints
    """
    df = quiq.copy()
    df['Variable_type'] = df['Variable_type'].astype(str)
    df['Is_categorical'] = pd.to_numeric(df['Is_categorical'], errors='coerce')

    df = df[df['Variable_type'].str.contains('numeric', case=False, na=False)]
    df = df[df['Is_categorical'] == 0]
    df['Value'] = df['Value'].apply(lambda v: Decimal(str(v)) if pd.notna(v) else np.nan)
    df = df.dropna(subset=['Value']).reset_index(drop=True)

    assert len(df) > 0, 'No numeric non-categorical values found.'

    filtered = df.groupby('Variable_name').filter(lambda x: len(x) > 1000)
    assert len(filtered) > 0, 'FAIL: No variables with more than 1000 data items.'

    labellist = (
        filtered.groupby(['Original_table_name', 'Variable_name'])
        .size()
        .sort_values(ascending=False)
        .index
        .tolist()
    )

    rows = []
    histogram_values = {}

    for table_name, var_name in labellist:
        print(f'{table_name} - {var_name}')

        dftemp = (
            df[(df['Original_table_name'] == table_name) & (df['Variable_name'] == var_name)]
            [['Original_table_name', 'Variable_name', 'Patient_id', 'Event_date', 'Value']]
            .dropna(subset=['Value'])
            .reset_index(drop=True)
        )
        dftemp['Value'] = dftemp['Value'].apply(_round_at_3)

        decimalnum, last_digits = _detect_decimal_scale(dftemp['Value'])
        gini, _ = _gini_simpson(last_digits)

        identifier = f'{table_name} - {var_name}'
        histogram_values[identifier] = last_digits
        rows.append({
            'Original_table_name': table_name,
            'Variable_name': var_name,
            'Total_num': len(dftemp),
            'Decimal_num': decimalnum,
            'Preciseness (%)': gini,
        })

    summary_df = pd.DataFrame(rows)
    summary_df['Total_num'] = summary_df['Total_num'].astype(int)
    summary_df['Decimal_num'] = summary_df['Decimal_num'].astype(int)

    return summary_df, histogram_values


if __name__ == '__main__':
    print('<LYDUS - Preciseness>\n')

    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=str, required=True)
    args = parser.parse_args()

    with open(args.config, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    quiq = pd.read_csv(config['quiq_path'])
    save_path = config['save_path']

    summary_df, histogram_values = get_preciseness(quiq)

    print('\nSave Results...')
    total_num = summary_df['Total_num'].sum()
    weighted_preciseness = round((summary_df['Total_num'] * summary_df['Preciseness (%)']).sum() / total_num, 2)

    with open(os.path.join(save_path, 'preciseness_total.txt'), 'w', encoding='utf-8') as f:
        f.write(f'Preciseness (%) = {weighted_preciseness}\n')

    summary_df.to_csv(os.path.join(save_path, 'preciseness_summary.csv'), index=False)

    hist_dir = os.path.join(save_path, 'preciseness_histograms')
    os.makedirs(hist_dir, exist_ok=True)

    summary_df['Identifier'] = summary_df['Original_table_name'] + ' - ' + summary_df['Variable_name']
    for idx, identifier in enumerate(summary_df['Identifier']):
        draw_histogram(save_path, idx, identifier, histogram_values[identifier])

    print('\n<SUCCESS>')
