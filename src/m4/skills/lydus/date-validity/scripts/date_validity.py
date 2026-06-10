import gc
import yaml
import argparse
import datetime
import pandas as pd
import openai
from dateutil.parser import parse
from tqdm import tqdm


SYSTEM_CONTENT = """We will evaluate the quality of the medical data
I want to verify that the date given is valid.
Please answer with 'yes' or 'no'.
No other answer than 'yes' or 'no'.
"""

KOREAN_DATE_FORMATS = [
    "%Y년 %m월 %d일",
    "%Y %m월 %d일",
    "%Y년 %m %d일",
    "%Y년 %m월 %d",
    "%Y %m월 %d",
    "%Y %m %일",
]


def _valid_date_custom(date_string: str) -> bool:
    for fmt in KOREAN_DATE_FORMATS:
        try:
            datetime.datetime.strptime(date_string, fmt)
            return True
        except ValueError:
            pass
    return False


def _is_valid_date(date_string) -> bool:
    if isinstance(date_string, pd.Timestamp):
        return True
    try:
        parse(str(date_string))
        return True
    except ValueError:
        return False


def _gpt_chat(client, model, user_content, temperature=0, max_tokens=10, n=1):
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_CONTENT},
            {"role": "user", "content": user_content}
        ],
        temperature=temperature,
        max_tokens=max_tokens,
        n=n
    )
    return [choice.message.content for choice in response.choices]


def _validate_date_entry(date_string, client, model) -> bool | None:
    if _is_valid_date(date_string):
        return True
    if _valid_date_custom(str(date_string)):
        return True

    # LLM fallback for ambiguous strings
    print(f'  → LLM fallback: {date_string}')
    try:
        result = _gpt_chat(client, model, f"date : {date_string}")
        answer = result[0].strip().lower() if result else ""
        if "no" in answer:
            return False
        elif "yes" in answer:
            return True
        else:
            return None
    except Exception as e:
        print(f"Failed to call LLM: {e}")
        return None


def _extract_date_data_mapping(df: pd.DataFrame) -> pd.DataFrame:
    record_dates_df = df[['Original_table_name', 'Event_date']].dropna().copy()
    record_dates_df['Variable_name'] = 'Event_date'
    record_dates_df.rename(columns={'Event_date': 'Date_value'}, inplace=True)

    date_mapping_df = df[df['Mapping_info_1'].str.contains('date', case=False, na=False)].copy()
    date_mapping_df = date_mapping_df[['Original_table_name', 'Variable_name', 'Value']].dropna()
    date_mapping_df.rename(columns={'Value': 'Date_value'}, inplace=True)

    combined = pd.concat([record_dates_df, date_mapping_df])
    return combined[['Original_table_name', 'Variable_name', 'Date_value']]


def get_date_validity(quiq: pd.DataFrame, model: str, api_key: str):
    """
    Parameters
    ----------
    quiq    : QUIQ-format DataFrame
    model   : OpenAI model name (e.g. 'gpt-4o-mini')
    api_key : OpenAI API key (pass None to disable LLM fallback)

    Returns
    -------
    valid_results_df : per-row validation result (Date_value, Is_valid)
    summary_df       : per-variable summary (Total_date, Invalid_date, Date_Validity_(%))
    """
    client = openai.OpenAI(api_key=api_key) if api_key else None

    df = quiq.copy()
    df['Mapping_info_1'] = df['Mapping_info_1'].astype(str)

    final_date_df = _extract_date_data_mapping(df)
    assert len(final_date_df) > 0, 'FAIL : No date values.'

    grouped_idx = final_date_df.groupby(['Original_table_name', 'Variable_name']).count().index

    tqdm.pandas()
    summary_rows = []
    valid_results_parts = []

    for idx in grouped_idx:
        table_name, variable_name = idx[0], idx[1]
        print(f'\n{table_name} - {variable_name}')

        temp = final_date_df[
            (final_date_df['Original_table_name'] == table_name) &
            (final_date_df['Variable_name'] == variable_name)
        ].copy()

        if client:
            temp['Is_valid'] = temp['Date_value'].progress_apply(
                lambda x: _validate_date_entry(x, client, model)
            )
        else:
            temp['Is_valid'] = temp['Date_value'].apply(
                lambda x: _is_valid_date(x) or _valid_date_custom(str(x))
            )

        total_date = len(temp)
        valid_date = temp['Is_valid'].sum()
        invalid_date = total_date - valid_date
        date_validity = round(valid_date / total_date * 100, 2)

        summary_rows.append({
            'Original_table_name': table_name,
            'Variable_name': variable_name,
            'Total_date': total_date,
            'Invalid_date': invalid_date,
            'Date_Validity_(%)': date_validity
        })

        valid_results_parts.append(temp)
        gc.collect()

    summary_df = pd.DataFrame(summary_rows)
    valid_results_df = pd.concat(valid_results_parts, axis=0) if valid_results_parts else pd.DataFrame()

    return valid_results_df, summary_df


if __name__ == '__main__':
    print('<LYDUS - Date Validity>')

    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=str, required=True)
    args = parser.parse_args()

    with open(args.config, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    quiq = pd.read_csv(config['quiq_path'])
    save_path = config['save_path']
    model_ver = config.get('model_ver', 'gpt-4o-mini')
    api_key = config.get('api_key')

    valid_results_df, summary_df = get_date_validity(quiq, model_ver, api_key)

    total_date = summary_df['Total_date'].sum()
    invalid_date = summary_df['Invalid_date'].sum()
    date_validity = round((total_date - invalid_date) / total_date * 100, 2)

    with open(save_path + '/date_validity_total.txt', 'w', encoding='utf-8') as f:
        f.write(f'Date Validity (%) = {date_validity}\n')
        f.write(f'Total dates = {total_date}\n')
        f.write(f'Invalid dates = {invalid_date}\n')

    valid_results_df.to_csv(save_path + '/date_validity_detail.csv', index=False)
    summary_df.to_csv(save_path + '/date_validity_summary.csv', index=False)

    print('\n<SUCCESS>')
