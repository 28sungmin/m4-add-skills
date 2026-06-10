import os
import re
import yaml
import argparse
import pandas as pd
import matplotlib.pyplot as plt
from collections import Counter
from matplotlib.axes import Axes

import nltk
# Ensure required NLTK data is available
for pkg in ['punkt', 'averaged_perceptron_tagger', 'punkt_tab', 'averaged_perceptron_tagger_eng']:
    try:
        nltk.data.find(f'tokenizers/{pkg}' if 'punkt' in pkg else f'taggers/{pkg}')
    except LookupError:
        nltk.download(pkg, quiet=True)

from nltk.tokenize import word_tokenize
from nltk.tag import pos_tag


def draw_sentence_diversity_histogram(ax: Axes, item_vs_percentage: dict, n: int = 10):
    ax.clear()
    items = list(item_vs_percentage.keys())[:n]
    percentages = [item_vs_percentage[k] for k in items]
    ax.bar(items, percentages)
    ax.set_xlabel('Items')
    ax.set_ylabel('Percentage (%)')
    ax.set_xticklabels(ax.get_xticklabels(), rotation=45)


def _custom_sent_tokenize(text: str) -> list:
    if not isinstance(text, str) or not text.strip():
        return []
    return re.split(r'(?<!\n)\n{2,}|[^\w\s\n,]+', text)


def _verb_sentences(text: str) -> list:
    """Extract sentences that contain at least one verb (POS tag starting with VB)."""
    result = []
    for sentence in _custom_sent_tokenize(text):
        words = word_tokenize(sentence)
        tags = pos_tag(words)
        if any(re.match(r'\bVB', tag) for _, tag in tags):
            result.append(sentence.strip())
    return result


def _counter_topn_items(total_count: int, counter: Counter, top_n: int = 10) -> tuple:
    if total_count == 0:
        return [], []
    top = counter.most_common(top_n)
    items = [item for item, _ in top]
    percentages = [round(count / total_count * 100, 2) for _, count in top]
    return items, percentages


def _coverage_of_top_pct(total_count: int, counter: Counter, pct: float) -> float:
    """% of total sentences covered by the top `pct`% most frequent unique sentences."""
    if total_count == 0:
        return 0.0
    top_k = int(len(counter) * pct / 100)
    top_sum = sum(count for _, count in counter.most_common(top_k))
    return round(top_sum / total_count * 100, 2)


def get_sentence_diversity(quiq: pd.DataFrame, top_n: int = 10) -> tuple:
    """
    Parameters
    ----------
    quiq  : QUIQ-format DataFrame
    top_n : number of top sentences to include in the histogram dict

    Returns
    -------
    sen_diversity     : Sentence Diversity (%) = unique / total × 100
    item_vs_percentage: dict mapping sentence → % for top-ALL sentences (sorted by freq)
    coverage_scores   : {5: %, 10: %, 20: %} — coverage of top-5/10/20% unique types
    freq_df           : DataFrame with Sentence, Count, Percentage columns
    """
    df = quiq.copy()
    df['Mapping_info_1'] = df['Mapping_info_1'].astype(str)

    df_note = df[df['Mapping_info_1'].str.contains('note', case=False, na=False)].copy()
    assert len(df_note) > 0, 'FAIL: No note rows (Mapping_info_1 containing "note") found.'

    df_note['TEXT_Verb'] = df_note['Value'].apply(_verb_sentences)
    all_sentences = [s for sublist in df_note['TEXT_Verb'] for s in sublist]

    total_count = len(all_sentences)
    unique_count = len(set(all_sentences))
    sen_diversity = round(unique_count / total_count * 100, 2) if total_count > 0 else 0.0

    counter = Counter(all_sentences)

    # item_vs_percentage: ALL unique sentences sorted by frequency
    items, percentages = _counter_topn_items(total_count, counter, top_n=total_count)
    item_vs_percentage = {item: pct for item, pct in zip(items, percentages)}

    coverage_scores = {
        pct: _coverage_of_top_pct(total_count, counter, pct)
        for pct in [5, 10, 20]
    }

    freq_df = pd.DataFrame(counter.items(), columns=['Sentence', 'Count'])
    freq_df['Percentage'] = round(freq_df['Count'] / total_count * 100, 2)

    return sen_diversity, item_vs_percentage, coverage_scores, freq_df


if __name__ == '__main__':
    print('<LYDUS - Sentence Diversity>\n')

    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=str, required=True)
    args = parser.parse_args()

    with open(args.config, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    quiq = pd.read_csv(config['quiq_path'])
    save_path = config['save_path']
    top_n = config.get('top_n', 10)

    sen_diversity, item_vs_percentage, coverage_scores, freq_df = get_sentence_diversity(
        quiq=quiq,
        top_n=top_n,
    )

    freq_df = freq_df.sort_values(by='Percentage', ascending=False)
    freq_df.to_csv(os.path.join(save_path, 'sentence_diversity_frequency.csv'), index=False)

    with open(os.path.join(save_path, 'sentence_diversity_summary.txt'), 'w', encoding='utf-8') as f:
        f.write(f'Sentence Diversity (%) = {sen_diversity}\n')
        f.write('Coverage Scores (Top %):\n')
        for k, v in coverage_scores.items():
            f.write(f'  Top {k}%: {v}\n')

    fig, ax = plt.subplots(figsize=(8, 5))
    draw_sentence_diversity_histogram(ax, item_vs_percentage, n=top_n)
    fig.tight_layout()
    fig.savefig(os.path.join(save_path, 'sentence_diversity_plot.png'))
    plt.close(fig)

    print(f'Sentence Diversity (%) = {sen_diversity}')
    for k, v in coverage_scores.items():
        print(f'  Top {k}% sentences cover {v}% of total')
    print('\n<SUCCESS>')
