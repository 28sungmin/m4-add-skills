import os
import ast
import yaml
import argparse
import numpy as np
import pandas as pd
import openai


_SYSTEM_PROMPT = """
As a data analyst in a healthcare setting, your task is to validate the sequential ordering of time-related fields within medical datasets. The aim is to uphold the data quality by ensuring the chronological order of medical events as recorded across various hospitals.

Procedure:
- CSV File Analysis: Review CSV files from medical data, noting that variable names may vary in terms of explicitness and abbreviation.
- Chronological Understanding: Establish the chronological order of events based on the time-related variables within the medical data.
- Exclude Non-Time Variables: Any variable that does not represent a time point should be excluded (e.g., location, status codes, categorical data).
- Exclude Unpaired Time Variables: If a variable representing a start time does not have a corresponding end time (or vice versa), it should be excluded from the pairing process.
- Exclude Sensitive or Complex Time Variables: Variables that are sensitive in nature (like 'death_time' or 'year_of_birth') or that have complex relationships (like 'diagnosis_date' preceding 'admission_date') that require additional context should be excluded from direct pairing.
- Exclude additional context variables such as ('insertion date' preceding 'tubing change') that require additional context.
- Create Time Variable Pairs: Only after exclusions have been identified, formulate pairs of time-related variables that logically represent the beginning and end of an event or process.
- Validate and Finalize Sequence: Confirm that the pairs are in a universally applicable sequence, according to the dataset's context.
- Preserve Original Formatting: Maintain the exact case and naming of the variable names from the dataset.
- Universal Sequences: Focus on sequences with broad applicability, like medication start and end dates.
- Avoid Assumptions: Steer clear of inferring fixed orders where they may not universally apply.
- Circumvent Presumptive Sequences: Refrain from deducing sequences where the order is not consistently established.
- Case Sensitivity: Retain the exact case (uppercase or lowercase) of the original column names in the output.
Once exclusions are identified, proceed to create the output without including any of the excluded variables.

Input or output variable format has to be 'Original_table_name - Variable_name'.

Example:
Input Format: ADMISSION - admission_time, ADMISSION - discharge_time, PATIENT - death_time, EMERGENCY - emergencyreg_time, EMERGENCY - emergencyout_time, PATIENT - dateofbirth
Output Format: timepoint_pairs = [
    ('ADMISSION - admission_time', 'ADMISSION - discharge_time'),
    ('EMERGENCY - emergencyreg_time', 'EMERGENCY - emergencyout_time'),
]
"""


def _llm_identify_pairs(client, model: str, unique_variables_string: str) -> list:
    """Ask LLM to identify (start, end) date-variable pairs from the identifier list."""
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": unique_variables_string},
        ],
        temperature=0,
        max_tokens=1200,
        top_p=1,
        frequency_penalty=0,
        presence_penalty=0,
    )
    gpt_output = response.choices[0].message.content
    print(f'\nLLM output:\n{gpt_output}\n')

    try:
        pairs_str = gpt_output.split('=', 1)[1].strip()
        pairs = ast.literal_eval(pairs_str)
        if not isinstance(pairs, list):
            raise ValueError(f'Expected list, got {type(pairs)}')
        return pairs
    except Exception as e:
        raise ValueError(
            f'Failed to parse LLM response as timepoint_pairs list.\n'
            f'Raw output: {gpt_output}\nError: {e}'
        )


def _validate_sequence(dataset: pd.DataFrame, timepoint_pairs: list) -> pd.DataFrame:
    """For each (start, end) pair, merge and check start_date <= end_date."""
    result_rows = []

    for start, end in timepoint_pairs:
        print(f"Compare '{start}' & '{end}'")
        try:
            start_table, start_var = start.split(' - ', 1)
            end_table, end_var = end.split(' - ', 1)
        except ValueError:
            print(f'SKIP - Cannot parse pair: ({start}, {end})')
            continue

        if start_table != end_table:
            print('SKIP - Different tables; accurate comparison is difficult.')
            continue

        start_df = (
            dataset[dataset['Variable_name'] == start_var]
            [['Patient_id', 'Primary_key', 'Original_table_name', 'Variable_name', 'Value']]
            .dropna()
            .rename(columns={'Variable_name': 'Start_var', 'Value': 'Start_date'})
        )
        end_df = (
            dataset[dataset['Variable_name'] == end_var]
            [['Patient_id', 'Primary_key', 'Original_table_name', 'Variable_name', 'Value']]
            .dropna()
            .rename(columns={'Variable_name': 'End_var', 'Value': 'End_date'})
        )

        merged = pd.merge(start_df, end_df, on=['Patient_id', 'Original_table_name', 'Primary_key'])
        if len(merged) == 0:
            print('  → No matching rows after merge.')
            continue

        merged['Is_valid'] = merged['Start_date'] <= merged['End_date']
        result_rows.append(merged)

    if not result_rows:
        return pd.DataFrame(columns=[
            'Patient_id', 'Primary_key', 'Original_table_name',
            'Start_var', 'Start_date', 'End_var', 'End_date', 'Is_valid'
        ])
    return pd.concat(result_rows, ignore_index=True)


def get_sequence_validity(quiq: pd.DataFrame, model: str, api_key: str):
    """
    Parameters
    ----------
    quiq    : QUIQ-format DataFrame
    model   : OpenAI model name (e.g. 'gpt-4o-mini')
    api_key : OpenAI API key

    Returns
    -------
    df_total   : per-row detail with Is_valid boolean
    df_summary : per-(table, start_var, end_var) summary with Sequence_Validity (%)
    """
    data = quiq.copy()
    data['Mapping_info_1'] = data['Mapping_info_1'].astype(str)

    date_df = data[data['Mapping_info_1'].str.contains('date', case=False, na=False)].copy()
    assert len(date_df) > 0, 'FAIL: No date rows (Mapping_info_1 containing "date") found.'

    date_df['Value'] = pd.to_datetime(date_df['Value'], errors='coerce')
    date_df['Identifier'] = date_df['Original_table_name'] + ' - ' + date_df['Variable_name']
    unique_names = date_df['Identifier'].unique().tolist()
    unique_variables_string = ', '.join(unique_names)

    client = openai.OpenAI(api_key=api_key)
    timepoint_pairs = _llm_identify_pairs(client, model, unique_variables_string)
    print(f'Identified pairs: {timepoint_pairs}')

    df_total = _validate_sequence(date_df, timepoint_pairs)

    if len(df_total) == 0:
        df_summary = pd.DataFrame(columns=[
            'Original_table_name', 'Start_var', 'End_var',
            'Total_num', 'Invalid_num', 'Sequence_Validity (%)'
        ])
        return df_total, df_summary

    df_summary = (
        df_total
        .groupby(['Original_table_name', 'Start_var', 'End_var'])
        .agg(Valid_num=('Is_valid', 'sum'), Total_num=('Primary_key', 'count'))
        .reset_index()
    )
    df_summary['Sequence_Validity (%)'] = np.round(
        df_summary['Valid_num'] / df_summary['Total_num'] * 100, 2
    )
    df_summary['Invalid_num'] = df_summary['Total_num'] - df_summary['Valid_num']
    df_summary = df_summary[[
        'Original_table_name', 'Start_var', 'End_var',
        'Total_num', 'Invalid_num', 'Sequence_Validity (%)'
    ]]

    return df_total, df_summary


if __name__ == '__main__':
    print('<LYDUS - Sequence Validity>\n')

    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=str, required=True)
    args = parser.parse_args()

    with open(args.config, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    quiq = pd.read_csv(config['quiq_path'])
    save_path = config['save_path']

    df_total, df_summary = get_sequence_validity(
        quiq=quiq,
        model=config['model_ver'],
        api_key=config['api_key'],
    )

    total_num = df_summary['Total_num'].sum()
    invalid_num = df_summary['Invalid_num'].sum()
    sequence_validity = round((total_num - invalid_num) / total_num * 100, 2) if total_num > 0 else 0.0

    with open(os.path.join(save_path, 'sequence_validity_total.txt'), 'w', encoding='utf-8') as f:
        f.write(f'Sequence Validity (%) = {sequence_validity}\n')
        f.write(f'Total Num = {total_num}\n')
        f.write(f'Invalid Num = {invalid_num}\n')

    df_total.to_csv(os.path.join(save_path, 'sequence_validity_detail.csv'), index=False)
    df_summary.to_csv(os.path.join(save_path, 'sequence_validity_summary.csv'), index=False)

    print('\n<SUCCESS>')
