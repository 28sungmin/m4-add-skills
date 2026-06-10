import gc
import re
import yaml
import argparse
import numpy as np
import pandas as pd
import openai
import statsmodels.formula.api as smf
import torch
import torch.nn as nn
from sklearn.ensemble import GradientBoostingRegressor as GBR
from sklearn.svm import OneClassSVM
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import RobustScaler
from torch.utils.data import TensorDataset, DataLoader


# ── LLM helpers ───────────────────────────────────────────────────

def _make_var_list_text(var_list) -> str:
    return ', '.join(f"'{v}'" for v in var_list)


def llm_ask_sex(client, model_ver: str, var_list_text: str) -> str | None:
    system_prompt = (
        "You are a medical data expert.\n"
        "A list of variable names will be provided.\n"
        "From the provided variables, select exactly one variable that is most relevant to **biological sex**.\n"
        "Respond with **only** the variable name, no additional explanation.\n"
        "And return it **exactly as it appears** in the provided list.\n"
        "If no appropriate variable is found, respond with 'None'."
    )
    response = client.chat.completions.create(
        model=model_ver,
        messages=[
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': f'List of variable names : {var_list_text}'}
        ],
        temperature=0
    )
    result = response.choices[0].message.content.strip()
    return None if result == 'None' else result.replace("'", '')


def llm_ask_birthdate(client, model_ver: str, var_list_text: str) -> str | None:
    system_prompt = (
        "You are a medical data expert.\n"
        "A list of variable names will be provided.\n"
        "From the provided variables, select exactly one variable that is most relevant to **date of birth**.\n"
        "Respond with **only** the variable name, no additional explanation.\n"
        "And return it **exactly as it appears** in the provided list.\n"
        "If no appropriate variable is found, respond with 'None'."
    )
    response = client.chat.completions.create(
        model=model_ver,
        messages=[
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': f'List of variable names : {var_list_text}'}
        ],
        temperature=0
    )
    result = response.choices[0].message.content.strip()
    return None if result == 'None' else result.replace("'", '')


def llm_ask_recommend(client, model_ver: str, var_name_target: str, n: int, var_list_text: str) -> list:
    system_prompt = (
        f"You are a medical data expert.\n\n"
        f"Your will be provided with :\n"
        f"- A target variable\n"
        f"- A list of variable names\n\n"
        f"Your task it to :\n"
        f"select the **top {n}** variables from the list that are **most relevant** to the target variable.\n\n"
        f"Important Rules :\n"
        f"1. Do **not include** the target variable itself in the output.\n"
        f"2. Return exactly {n} variable names, seperate them by **!**.\n"
        f"3. Do **not repeat** any variable name - all must be unique.\n"
        f"4. Return the variable names **exactly as it appears** in the provided list.\n"
        f"5. Do **not include** any additional explanation."
    )
    response = client.chat.completions.create(
        model=model_ver,
        messages=[
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': f'Target variable : {var_name_target}\nList of variable names : {var_list_text}'}
        ],
        temperature=0
    )
    text = response.choices[0].message.content.replace("'", '')
    recommended = text.split('!')
    print(f'RECOMMENDED VARIABLES : {recommended}')
    return recommended


# ── Autoencoder ───────────────────────────────────────────────────

class Autoencoder(nn.Module):
    def __init__(self, input_dim: int):
        super().__init__()
        self.encoder = nn.Sequential(
            nn.Linear(input_dim, int(input_dim // 1.3)),
            nn.Tanh(),
            nn.Linear(int(input_dim // 1.3), int(input_dim // 2))
        )
        self.decoder = nn.Sequential(
            nn.Linear(int(input_dim // 2), int(input_dim // 1.3)),
            nn.Tanh(),
            nn.Linear(int(input_dim // 1.3), input_dim)
        )

    def forward(self, x):
        return self.decoder(self.encoder(x))


def _train_autoencoder(Input_scaled: torch.Tensor, device) -> nn.Module:
    dataset = TensorDataset(Input_scaled)
    loader = DataLoader(dataset, batch_size=64, shuffle=True)

    model = Autoencoder(input_dim=Input_scaled.shape[1]).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
    criterion = nn.MSELoss()

    best_loss = float('inf')
    counter = 0
    patience = 5
    min_delta = 1e-3

    for epoch in range(1, 501):
        model.train()
        total_loss, total_sample = 0, 0
        for (inputs,) in loader:
            inputs = inputs.to(device)
            loss = criterion(model(inputs), inputs)
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            total_loss += loss.item() * inputs.shape[0]
            total_sample += inputs.shape[0]

        now_loss = total_loss / total_sample
        print(f'Epoch {epoch} | Loss : {round(now_loss, 3)}')

        if best_loss - now_loss > min_delta:
            best_loss = now_loss
            counter = 0
        else:
            counter += 1

        if counter >= patience:
            break
        if epoch > 500 and now_loss < 1:
            break

    print('STOP TRAINING')
    return model


# ── Main function ─────────────────────────────────────────────────

def get_logical_accuracy(
        quiq: pd.DataFrame,
        model_ver: str,
        api_key: str,
        operation_type_manual: bool,
        target_variable: str,
        automatic_num: int,
        recommend_num: int):
    """
    Parameters
    ----------
    quiq                  : QUIQ-format DataFrame
    model_ver             : OpenAI model name (e.g. 'gpt-4o-mini')
    api_key               : OpenAI API key
    operation_type_manual : True = manual target selection, False = automatic (top-N by count)
    target_variable       : target variable name (used when operation_type_manual=True)
    automatic_num         : number of top variables to analyze (used when operation_type_manual=False)
    recommend_num         : number of correlated variables recommended by LLM
    """
    client = openai.OpenAI(api_key=api_key)
    gc.collect()

    df_quiq = quiq.copy()
    df_quiq['Event_date'] = pd.to_datetime(df_quiq['Event_date'], errors='coerce')
    df_quiq['Mapping_info_1'] = df_quiq['Mapping_info_1'].astype(str)
    df_quiq['Mapping_info_2'] = df_quiq['Mapping_info_2'].astype(str)
    df_quiq['Variable_type'] = df_quiq['Variable_type'].astype(str)
    df_quiq['Is_categorical'] = pd.to_numeric(df_quiq['Is_categorical'], errors='coerce')

    # ── Sex variable ───────────────────────────────────────────────
    df_sex_quiq = df_quiq[df_quiq['Is_categorical'] == 1]
    var_list_sex = df_sex_quiq['Variable_name'].unique()
    if len(var_list_sex) > 0:
        var_name_sex = llm_ask_sex(client, model_ver, _make_var_list_text(var_list_sex))
    else:
        var_name_sex = None
    print(f'FIND SEX VARIABLE : {var_name_sex}\n')

    df_sex_essential = df_sex_quiq[df_sex_quiq['Variable_name'] == var_name_sex][['Value', 'Patient_id']].dropna()

    # ── Birthdate variable ─────────────────────────────────────────
    df_birthdate_quiq = df_quiq[df_quiq['Mapping_info_1'] == 'date']
    var_list_birthdate = df_birthdate_quiq['Variable_name'].unique()
    if len(var_list_birthdate) > 0:
        var_name_birthdate = llm_ask_birthdate(client, model_ver, _make_var_list_text(var_list_birthdate))
    else:
        var_name_birthdate = None
    print(f'FIND BIRTHDATE VARIABLE : {var_name_birthdate}\n')

    df_birthdate_essential = df_birthdate_quiq[df_birthdate_quiq['Variable_name'] == var_name_birthdate][['Value', 'Patient_id']].copy()
    df_birthdate_essential['Value'] = pd.to_datetime(df_birthdate_essential['Value'], errors='coerce')
    df_birthdate_essential = df_birthdate_essential.dropna()
    gc.collect()

    # ── Filter clinical data ───────────────────────────────────────
    print('FILTER CATEGORY VALUES\n')
    df_event_quiq = df_quiq[
        df_quiq['Mapping_info_1'].str.contains('event', case=False, na=False) &
        df_quiq['Variable_type'].str.contains('numeric', case=False, na=False) &
        (df_quiq['Is_categorical'] == 0)
    ].copy()
    df_event_quiq['Value'] = pd.to_numeric(df_event_quiq['Value'], errors='coerce')
    df_event_quiq = df_event_quiq.dropna(subset=['Value', 'Event_date'])

    df_diagnosis_quiq = df_quiq[
        df_quiq['Mapping_info_1'].str.contains('diagnosis', case=False, na=False) &
        (df_quiq['Is_categorical'] == 1)
    ].dropna(subset=['Value', 'Event_date'])

    df_prescription_quiq = df_quiq[
        df_quiq['Mapping_info_1'].str.contains('prescription', case=False, na=False) &
        df_quiq['Mapping_info_2'].str.contains('drug', case=False, na=False) &
        (df_quiq['Is_categorical'] == 1)
    ].dropna(subset=['Value', 'Event_date'])

    df_procedure_quiq = df_quiq[
        df_quiq['Mapping_info_1'].str.contains('procedure', case=False, na=False) &
        (df_quiq['Is_categorical'] == 1)
    ].dropna(subset=['Value', 'Event_date'])

    df_others_quiq = pd.concat([df_diagnosis_quiq, df_prescription_quiq, df_procedure_quiq], axis=0)
    assert len(df_event_quiq) + len(df_others_quiq) > 0, \
        'FAIL - No available data related to event, diagnosis, prescription, procedure.'

    del df_diagnosis_quiq, df_prescription_quiq, df_procedure_quiq
    gc.collect()

    # ── Select target variables ────────────────────────────────────
    if operation_type_manual:
        evaluate_mode = [-1]
        if target_variable in df_event_quiq['Variable_name'].unique():
            var_list_target = [target_variable]
            evaluate_mode[0] = 0
        elif target_variable in df_others_quiq['Value'].unique():
            var_list_target = [target_variable]
            evaluate_mode[0] = 1
        else:
            assert False, 'FAIL - Invalid target variable name. Please check and try again.'
    else:
        evaluate_mode = [-1] * automatic_num
        var_list_target = [''] * automatic_num

        df_others_quiq['Dummy'] = df_others_quiq['Value'].copy()
        count_event = df_event_quiq.groupby('Variable_name').agg(
            Count=('Value', 'count'), Category=('Mapping_info_1', 'first')
        ).reset_index()[['Variable_name', 'Count', 'Category']]
        count_others = df_others_quiq.groupby('Value').agg(
            Count=('Dummy', 'count'), Category=('Mapping_info_1', 'first')
        ).reset_index()[['Value', 'Count', 'Category']].rename(columns={'Value': 'Variable_name'})

        count_all = pd.concat([count_event, count_others]).sort_values(by='Count', ascending=False).reset_index(drop=True)
        del count_event, count_others
        gc.collect()

        for idx in range(automatic_num):
            var_list_target[idx] = count_all.at[idx, 'Variable_name']
            evaluate_mode[idx] = 0 if 'event' in count_all.at[idx, 'Category'].lower() else 1

    print(f'SET TARGET VARIABLES : {var_list_target}')

    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    dict_total = {}
    dict_outlier = {}

    for loop, var_name_target in enumerate(var_list_target):
        flag = 0
        print(f'\n# LOOP {loop+1} - Target Variable : {var_name_target}\n')
        var_evaluate_mode = evaluate_mode[loop]

        if var_evaluate_mode == 0:
            df_target_essential = df_event_quiq[df_event_quiq['Variable_name'].isin([var_name_target])][
                ['Original_table_name', 'Variable_name', 'Event_date', 'Value', 'Patient_id']
            ]
            df_event_quiq = df_event_quiq[~df_event_quiq['Variable_name'].isin([var_name_target])]
        else:
            df_target_essential = df_others_quiq[df_others_quiq['Value'].isin([var_name_target])][
                ['Original_table_name', 'Variable_name', 'Event_date', 'Value', 'Patient_id']
            ]
            df_others_quiq = df_others_quiq[~df_others_quiq['Value'].isin([var_name_target])]

        # Top-100 candidate variables
        df_event_essential = df_event_quiq[['Original_table_name', 'Variable_name', 'Event_date', 'Value', 'Patient_id']]
        var_list_event = df_event_essential.groupby('Variable_name').count().sort_values(by='Value', ascending=False).index[:100]
        df_event_essential = df_event_essential[df_event_essential['Variable_name'].isin(var_list_event)]

        df_others_quiq['Dummy'] = df_others_quiq['Value'].copy()
        df_others_essential = df_others_quiq[['Original_table_name', 'Variable_name', 'Event_date', 'Value', 'Patient_id', 'Dummy', 'Mapping_info_1']]
        var_list_diagnosis = df_others_essential[df_others_essential['Mapping_info_1'].str.contains('diagnosis', case=False, na=False)]\
            .groupby('Value').count().sort_values(by='Dummy', ascending=False).index[:100]
        var_list_prescription = df_others_essential[df_others_essential['Mapping_info_1'].str.contains('prescription', case=False, na=False)]\
            .groupby('Value').count().sort_values(by='Dummy', ascending=False).index[:100]
        var_list_procedure = df_others_essential[df_others_essential['Mapping_info_1'].str.contains('procedure', case=False, na=False)]\
            .groupby('Value').count().sort_values(by='Dummy', ascending=False).index[:100]
        df_others_essential = df_others_essential[df_others_essential['Value'].isin(
            var_list_diagnosis.tolist() + var_list_prescription.tolist() + var_list_procedure.tolist()
        )]
        gc.collect()

        # LLM: recommend correlated variables
        var_list_candidate = list(df_event_essential['Variable_name'].unique()) + list(df_others_essential['Value'].unique())
        var_list_recommended = llm_ask_recommend(
            client, model_ver, var_name_target, recommend_num, _make_var_list_text(var_list_candidate)
        )

        # ── Build clinical context vector ──────────────────────────
        print('MAKE CLINICAL CONTEXT VECTOR')
        dict_dynamic = {}

        if var_evaluate_mode == 0:
            dict_dynamic[var_name_target] = (
                df_target_essential[['Event_date', 'Patient_id', 'Value']]
                .groupby(['Patient_id', 'Event_date']).agg('median').reset_index()
                .rename(columns={'Event_date': 'Target_date', 'Value': f'{var_name_target}_val'})
            )
        else:
            tmp = df_target_essential[['Event_date', 'Patient_id', 'Value']].copy()
            tmp['Value'] = 1
            dict_dynamic[var_name_target] = tmp.rename(columns={'Event_date': 'Target_date', 'Value': f'{var_name_target}_val'})

        for var_name_recommended in var_list_recommended:
            if var_name_recommended in df_event_essential['Variable_name'].unique():
                dict_dynamic[var_name_recommended] = (
                    df_event_essential[df_event_essential['Variable_name'] == var_name_recommended][['Event_date', 'Patient_id', 'Value']]
                    .groupby(['Patient_id', 'Event_date']).agg('median').reset_index()
                    .rename(columns={'Value': f'{var_name_recommended}_val'})
                )
            else:
                tmp = df_others_essential[df_others_essential['Value'] == var_name_recommended][['Event_date', 'Patient_id', 'Value']].drop_duplicates()
                dict_dynamic[var_name_recommended] = tmp.rename(columns={'Value': f'{var_name_recommended}_val'})
            gc.collect()

        df_merged = dict_dynamic[var_name_target]

        for var_name_recommended in var_list_recommended:
            if var_name_recommended in df_event_essential['Variable_name'].unique():
                df_merged = pd.merge(df_merged, dict_dynamic[var_name_recommended], on='Patient_id', how='left').dropna()
                df_merged = df_merged[
                    (df_merged['Event_date'] >= df_merged['Target_date'] - pd.Timedelta(days=7)) &
                    (df_merged['Event_date'] <= df_merged['Target_date'])
                ].reset_index(drop=True)
                df_merged['Time_diff'] = (df_merged['Target_date'] - df_merged['Event_date']).dt.total_seconds()
                idx = df_merged.groupby(['Patient_id', 'Target_date', f'{var_name_target}_val'])['Time_diff'].idxmin()
                df_merged = df_merged.iloc[idx].reset_index(drop=True).drop(['Event_date', 'Time_diff'], axis=1)

            elif var_name_recommended in df_others_essential['Value'].unique():
                dict_dynamic[var_name_recommended][f'{var_name_recommended}_val'] = 1
                df_merged = pd.merge(df_merged, dict_dynamic[var_name_recommended], on='Patient_id', how='left')
                df_merged[f'{var_name_recommended}_val'] = df_merged[f'{var_name_recommended}_val'].fillna(0)

                with_date = df_merged[df_merged[f'{var_name_recommended}_val'] == 1]
                no_date = df_merged[df_merged[f'{var_name_recommended}_val'] == 0]
                with_date = with_date[
                    (with_date['Event_date'] >= with_date['Target_date'] - pd.Timedelta(days=7)) &
                    (with_date['Event_date'] <= with_date['Target_date'])
                ].reset_index(drop=True)
                with_date['Time_diff'] = (with_date['Target_date'] - with_date['Event_date']).dt.total_seconds()
                idx = with_date.groupby(['Patient_id', 'Target_date', f'{var_name_target}_val'])['Time_diff'].idxmin()
                with_date = with_date.iloc[idx].reset_index(drop=True)
                df_merged = pd.concat([with_date, no_date], axis=0).reset_index(drop=True).drop(['Event_date', 'Time_diff'], axis=1)
            else:
                print('FAIL - Variable name mismatch detected.')
                flag = 1
                break

        if flag == 1:
            continue
        gc.collect()

        if len(df_sex_essential) > 0:
            onehot_sex = pd.get_dummies(df_sex_essential['Value'], prefix='Sex').iloc[:, 1:].astype(int)
            df_sex_concat = pd.concat([df_sex_essential, onehot_sex], axis=1)
            df_merged = pd.merge(df_merged, df_sex_concat, on='Patient_id', how='left').dropna().drop(['Value'], axis=1)

        if len(df_birthdate_essential) > 0:
            df_merged = pd.merge(df_merged, df_birthdate_essential, on='Patient_id', how='left').dropna()
            df_merged = df_merged[df_merged['Target_date'] > df_merged['Value']]
            df_merged['Age'] = [(td.days / 365.25) for td in (df_merged['Target_date'].dt.to_pydatetime() - df_merged['Value'].dt.to_pydatetime())]
            df_merged = df_merged.drop(['Value'], axis=1)

        if len(df_merged) == 0:
            print('FAIL - Failed to construct the clinical context vector.')
            continue

        df_result = df_merged.copy()

        if var_evaluate_mode == 0:
            # ── Numeric: Quantile Regression + GBR + Autoencoder ──
            X = df_merged.drop(['Patient_id', 'Target_date', f'{var_name_target}_val'], axis=1)
            y = df_merged[f'{var_name_target}_val']
            X.columns = X.columns.str.replace(r'\W', '_', regex=True)
            y.name = re.sub(r'\W', '_', y.name)
            Xy = pd.concat([X, y], axis=1)

            print('LINEAR REGRESSION')
            for quantile in [0.01, 0.99]:
                model = smf.quantreg(f"{y.name} ~ " + ' + '.join(X.columns), Xy).fit(q=quantile)
                df_result[f'LR_{quantile}'] = model.predict(X)
            gc.collect()

            print('GRADIENT BOOSTING')
            X = df_merged.drop(['Patient_id', 'Target_date', f'{var_name_target}_val'], axis=1)
            y = df_merged[f'{var_name_target}_val']
            for quantile in [0.01, 0.99]:
                model = GBR(loss='quantile', alpha=quantile, min_samples_leaf=5, min_samples_split=5)
                df_result[f'GB_{quantile}'] = model.fit(X, y).predict(X)
            gc.collect()

            print('AUTOENCODER')
            X_raw = df_merged.drop(['Patient_id', 'Target_date'], axis=1)
            scaler = RobustScaler()
            X_scaled = torch.tensor(scaler.fit_transform(X_raw), dtype=torch.float32)
            ae_model = _train_autoencoder(X_scaled, device)
            ae_model.eval()
            with torch.no_grad():
                outputs = ae_model(X_scaled.to(device)).cpu().numpy()
            df_result['AE_output'] = scaler.inverse_transform(outputs)[:, 0]
            recon_error = abs(df_result['AE_output'] - df_result[f'{var_name_target}_val'])
            df_result['AE_0.98'] = np.quantile(recon_error, 0.98)
            gc.collect()

            dict_total[var_name_target] = df_result.copy()

            df_upper = df_result[
                (df_result[f'{var_name_target}_val'] > df_result['LR_0.99']) &
                (df_result[f'{var_name_target}_val'] > df_result['GB_0.99']) &
                (abs(df_result['AE_output'] - df_result[f'{var_name_target}_val']) > df_result['AE_0.98'])
            ].copy()
            df_upper['Direction'] = 'Upper'

            df_under = df_result[
                (df_result[f'{var_name_target}_val'] < df_result['LR_0.01']) &
                (df_result[f'{var_name_target}_val'] < df_result['GB_0.01']) &
                (abs(df_result['AE_output'] - df_result[f'{var_name_target}_val']) > df_result['AE_0.98'])
            ].copy()
            df_under['Direction'] = 'Under'

            dict_outlier[var_name_target] = pd.concat([df_upper, df_under], axis=0)

        else:
            # ── Categorical: OneClassSVM + IsolationForest + Autoencoder ──
            X_raw = df_merged.drop(['Patient_id', 'Target_date', f'{var_name_target}_val'], axis=1)

            print('SUPPORT VECTOR MACHINE')
            scaler = RobustScaler()
            X_scaled = scaler.fit_transform(X_raw)
            svm = OneClassSVM(kernel='rbf', nu=0.02, gamma='scale').fit(X_scaled)
            df_result['SVM_score'] = -svm.decision_function(X_scaled)
            df_result['SVM_0.98'] = np.quantile(df_result['SVM_score'], 0.98)
            gc.collect()

            print('ISOLATION FOREST')
            scaler = RobustScaler()
            X_scaled = scaler.fit_transform(X_raw)
            iso = IsolationForest(contamination=0.02).fit(X_scaled)
            df_result['IF_score'] = -iso.decision_function(X_scaled)
            df_result['IF_0.98'] = np.quantile(df_result['IF_score'], 0.98)
            gc.collect()

            print('AUTOENCODER')
            scaler = RobustScaler()
            X_scaled = torch.tensor(scaler.fit_transform(X_raw), dtype=torch.float32)
            ae_model = _train_autoencoder(X_scaled, device)
            ae_model.eval()
            with torch.no_grad():
                outputs = ae_model(X_scaled.to(device)).cpu().numpy()
            X_np = X_scaled.cpu().numpy()
            df_result['AE_error'] = np.mean(abs(outputs - X_np), axis=1)
            df_result['AE_0.98'] = np.quantile(df_result['AE_error'], 0.98)
            gc.collect()

            dict_total[var_name_target] = df_result.copy()
            dict_outlier[var_name_target] = df_result[
                (df_result['SVM_score'] > df_result['SVM_0.98']) &
                (df_result['IF_score'] > df_result['IF_0.98']) &
                (df_result['AE_error'] > df_result['AE_0.98'])
            ].copy()
            gc.collect()

        print()

    return var_list_target, dict_total, dict_outlier


if __name__ == '__main__':
    print('<LYDUS - Logical Accuracy>\n')

    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=str, required=True)
    args = parser.parse_args()

    with open(args.config, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    quiq = pd.read_csv(config['quiq_path'])
    save_path = config['save_path']
    model_ver = config['model_ver']
    api_key = config['api_key']
    operation_type_manual = bool(config.get('operation_type_manual', False))
    target_variable = config.get('target_variable', '')
    automatic_num = config.get('automatic_num', 5)
    recommend_num = config.get('recommend_num', 5)

    var_list_target, dict_total, dict_outlier = get_logical_accuracy(
        quiq, model_ver, api_key,
        operation_type_manual, target_variable, automatic_num, recommend_num
    )

    outlier_num = 0
    total_num = 0

    # fixed: original had missing comma → 'Outlier Num' 'Logical Accuracy (%)' merged into one column name
    summary_rows = []
    for idx, var_name_target in enumerate(var_list_target):
        try:
            t_num = len(dict_total[var_name_target])
            o_num = len(dict_outlier[var_name_target])
            accuracy = round((t_num - o_num) / t_num * 100, 2)
            total_num += t_num
            outlier_num += o_num
            summary_rows.append({
                'Target Variable': var_name_target,
                'Total Num': t_num,
                'Outlier Num': o_num,
                'Logical Accuracy (%)': accuracy
            })
            if o_num > 0:
                dict_outlier[var_name_target].to_csv(f'{save_path}/outlier_{idx}_{var_name_target}.csv', index=False)
        except Exception:
            summary_rows.append({
                'Target Variable': var_name_target,
                'Total Num': np.nan,
                'Outlier Num': np.nan,
                'Logical Accuracy (%)': np.nan
            })

    pd.DataFrame(summary_rows).to_csv(f'{save_path}/logical_accuracy_summary.csv', index=False)

    logical_accuracy = round((total_num - outlier_num) / total_num * 100, 2)
    with open(f'{save_path}/logical_accuracy_total.txt', 'w', encoding='utf-8') as f:
        f.write(f'Logical Accuracy (%) = {logical_accuracy}\n')
        f.write(f'Total Num = {total_num}\n')
        f.write(f'Outlier Num = {outlier_num}\n')

    print('<SUCCESS>')
