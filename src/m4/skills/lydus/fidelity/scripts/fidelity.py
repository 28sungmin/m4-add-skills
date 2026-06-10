import gc
import yaml
import argparse
import numpy as np
import pandas as pd


def get_structured_fidelity(quiq: pd.DataFrame) -> pd.DataFrame:
    df = quiq.copy()
    df['Mapping_info_1'] = df['Mapping_info_1'].astype(str)
    df['Mapping_info_2'] = df['Mapping_info_2'].astype(str)
    df['Variable_type'] = df['Variable_type'].astype(str)

    parts = []

    # ── ① Event ──────────────────────────────────────────────────────
    print('\nCategory : Event')
    df_event = df[df['Mapping_info_1'].str.contains('event', case=False, na=False)]
    df_event = df_event.dropna(subset=['Patient_id', 'Value'])

    if len(df_event) > 0:
        per_patient = df_event.groupby(
            ['Original_table_name', 'Variable_name', 'Patient_id']
        ).agg(Frequency=('Value', 'count')).reset_index()

        agg = per_patient.groupby(
            ['Original_table_name', 'Variable_name']
        ).agg(
            Patient_num=('Patient_id', 'nunique'),
            Mean=('Frequency', 'mean'),
            Std=('Frequency', 'std')
        ).reset_index()
        agg['Value'] = np.nan
        parts.append(agg)
    else:
        print("FAIL - No available values found in the 'Event' category.")

    gc.collect()

    # ── ② Diagnosis ──────────────────────────────────────────────────
    print('\nCategory : Diagnosis')
    df_diagnosis = df[df['Mapping_info_1'].str.contains('diagnosis', case=False, na=False)]
    df_diagnosis = df_diagnosis[pd.to_numeric(df_diagnosis['Is_categorical'], errors='coerce') == 1]
    df_diagnosis = df_diagnosis.dropna(subset=['Patient_id', 'Value'])

    if len(df_diagnosis) > 0:
        df_diagnosis = df_diagnosis.copy()
        per_patient = df_diagnosis.groupby(
            ['Original_table_name', 'Variable_name', 'Value', 'Patient_id']
        ).agg(Frequency=('Value', 'count')).reset_index()

        agg = per_patient.groupby(
            ['Original_table_name', 'Variable_name', 'Value']
        ).agg(
            Patient_num=('Patient_id', 'nunique'),
            Mean=('Frequency', 'mean'),
            Std=('Frequency', 'std')
        ).reset_index()
        parts.append(agg)
    else:
        print("FAIL - No available values found in the 'Diagnosis' category.")

    gc.collect()

    # ── ③ Prescription ───────────────────────────────────────────────
    print('\nCategory : Prescription')
    df_prescription = df[df['Mapping_info_1'].str.contains('prescription', case=False, na=False)]
    df_prescription = df_prescription[pd.to_numeric(df_prescription['Is_categorical'], errors='coerce') == 1]
    df_prescription = df_prescription.dropna(subset=['Patient_id', 'Value'])

    if len(df_prescription) > 0:
        df_prescription = df_prescription.copy()
        per_patient = df_prescription.groupby(
            ['Original_table_name', 'Variable_name', 'Value', 'Patient_id']
        ).agg(Frequency=('Value', 'count')).reset_index()

        agg = per_patient.groupby(
            ['Original_table_name', 'Variable_name', 'Value']
        ).agg(
            Patient_num=('Patient_id', 'nunique'),
            Mean=('Frequency', 'mean'),
            Std=('Frequency', 'std')
        ).reset_index()
        parts.append(agg)
    else:
        print("FAIL - No available values found in the 'Prescription' category.")

    gc.collect()

    # ── ④ Procedure ──────────────────────────────────────────────────
    print('\nCategory : Procedure')
    df_procedure = df[df['Mapping_info_1'].str.contains('procedure', case=False, na=False)]
    df_procedure = df_procedure[pd.to_numeric(df_procedure['Is_categorical'], errors='coerce') == 1]
    df_procedure = df_procedure.dropna(subset=['Patient_id', 'Value'])

    if len(df_procedure) > 0:
        df_procedure = df_procedure.copy()
        per_patient = df_procedure.groupby(
            ['Original_table_name', 'Variable_name', 'Value', 'Patient_id']
        ).agg(Frequency=('Value', 'count')).reset_index()

        agg = per_patient.groupby(
            ['Original_table_name', 'Variable_name', 'Value']
        ).agg(
            Patient_num=('Patient_id', 'nunique'),
            Mean=('Frequency', 'mean'),
            Std=('Frequency', 'std')
        ).reset_index()
        parts.append(agg)
    else:
        print("FAIL - No available values found in the 'Procedure' category.")

    df_results = pd.concat(parts, axis=0) if parts else pd.DataFrame(
        columns=['Original_table_name', 'Variable_name', 'Value', 'Patient_num', 'Mean', 'Std']
    )
    df_results['Mean'] = df_results['Mean'].round(2)
    df_results['Std'] = df_results['Std'].round(2)

    return df_results


if __name__ == '__main__':
    print('<LYDUS - Fidelity>')

    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=str, required=True)
    args = parser.parse_args()

    with open(args.config, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    quiq = pd.read_csv(config['quiq_path'])
    save_path = config['save_path']

    df_results = get_structured_fidelity(quiq)

    total_num = df_results['Patient_num'].sum()
    weighted_fidelity = round(
        (df_results['Patient_num'] * df_results['Mean']).sum() / total_num, 2
    )

    with open(save_path + '/fidelity_total.txt', 'w', encoding='utf-8') as f:
        f.write(f'Weighted Fidelity = {weighted_fidelity}\n')

    df_results.to_csv(save_path + '/fidelity_summary.csv', index=False)

    print('\n<SUCCESS>')
