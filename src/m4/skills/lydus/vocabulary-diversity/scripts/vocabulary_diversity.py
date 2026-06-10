import gc
import os
import re
import string
import yaml
import argparse
import nltk
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from collections import Counter
from typing import Dict, Tuple


def _ensure_nltk():
    for pkg in ('punkt', 'punkt_tab', 'averaged_perceptron_tagger', 'averaged_perceptron_tagger_eng'):
        try:
            nltk.data.find(f'tokenizers/{pkg}' if 'punkt' in pkg else f'taggers/{pkg}')
        except LookupError:
            nltk.download(pkg, quiet=True)


def _noun_words(text: str) -> list:
    """Return all NN* (noun) tokens from text."""
    if not isinstance(text, str):
        return []
    noun_pattern = re.compile(r'\bNN')
    from nltk.tokenize import word_tokenize
    from nltk.tag import pos_tag
    words = word_tokenize(text)
    pos_tags = pos_tag(words)
    nouns = [
        w.strip() for w, tag in pos_tags
        if noun_pattern.match(tag) and w not in string.punctuation
    ]
    return nouns


def _percentage_top_items(total_count: int, counter: Counter, pct: float) -> float:
    """Coverage: top `pct`% of unique word types → % of total word occurrences."""
    if total_count == 0:
        return 0.0
    top_k = int(len(counter) * pct / 100)
    top_sum = sum(cnt for _, cnt in counter.most_common(top_k))
    return round(top_sum / total_count * 100, 2)


def get_vocabulary_diversity(
    quiq: pd.DataFrame,
    top_n: int = 10,
) -> Tuple[float, Dict[str, float], Dict[float, float], pd.DataFrame]:
    """
    Parameters
    ----------
    quiq  : QUIQ-format DataFrame
    top_n : number of top words to show in the histogram

    Returns
    -------
    word_diversity   : float — unique_words / total_words × 100
    item_vs_pct      : dict[word → pct] sorted by frequency (all unique words)
    coverage_scores  : dict[5/10/20 → coverage pct]
    freq_df          : DataFrame with columns [Word, Count, Percentage]
    """
    _ensure_nltk()

    df = quiq.copy()
    df['Mapping_info_1'] = df['Mapping_info_1'].astype(str)

    df_note = df[df['Mapping_info_1'].str.contains('note', case=False, na=False)].copy()
    if len(df_note) == 0:
        print('FAIL: No note rows in data.')
        return 0.0, {}, {5: 0.0, 10: 0.0, 20: 0.0}, pd.DataFrame(columns=['Word', 'Count', 'Percentage'])

    df_note['_noun_words'] = df_note['Value'].apply(_noun_words)
    total_words = [w for sublist in df_note['_noun_words'].tolist() for w in sublist]

    total_count = len(total_words)
    if total_count == 0:
        print('FAIL: No noun words extracted.')
        return 0.0, {}, {5: 0.0, 10: 0.0, 20: 0.0}, pd.DataFrame(columns=['Word', 'Count', 'Percentage'])

    counter = Counter(total_words)
    unique_count = len(counter)
    word_diversity = round(unique_count / total_count * 100, 2)

    # Build item_vs_pct: all unique words sorted by frequency descending
    sorted_items = counter.most_common()
    item_vs_pct = {word: round(cnt / total_count * 100, 2) for word, cnt in sorted_items}

    coverage_scores = {pct: _percentage_top_items(total_count, counter, pct) for pct in (5, 10, 20)}

    freq_df = (
        pd.DataFrame(counter.items(), columns=['Word', 'Count'])
        .assign(Percentage=lambda d: round(d['Count'] / total_count * 100, 2))
        .sort_values('Percentage', ascending=False)
        .reset_index(drop=True)
    )

    gc.collect()
    return word_diversity, item_vs_pct, coverage_scores, freq_df


def draw_vocab_diversity_histogram(save_path: str, item_vs_pct: Dict[str, float], top_n: int):
    words = list(item_vs_pct.keys())[:top_n]
    pcts = list(item_vs_pct.values())[:top_n]
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.bar(words, pcts)
    ax.set_xlabel('Words')
    ax.set_ylabel('Percentage (%)')
    ax.set_title(f'Top {top_n} Most Frequent Nouns')
    ax.set_xticklabels(ax.get_xticklabels(), rotation=45, ha='right')
    fig.tight_layout()
    fig.savefig(os.path.join(save_path, 'vocabulary_diversity_plot.png'), facecolor='white')
    plt.close(fig)


if __name__ == '__main__':
    print('<LYDUS - Vocabulary Diversity>\n')

    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=str, required=True)
    args = parser.parse_args()

    with open(args.config, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    quiq = pd.read_csv(config['quiq_path'])
    save_path = config['save_path']
    top_n = config.get('top_n', 10)

    word_diversity, item_vs_pct, coverage_scores, freq_df = get_vocabulary_diversity(
        quiq=quiq,
        top_n=top_n,
    )

    os.makedirs(save_path, exist_ok=True)

    freq_df.to_csv(os.path.join(save_path, 'vocabulary_diversity_frequency.csv'), index=False, encoding='utf-8-sig')

    with open(os.path.join(save_path, 'vocabulary_diversity_summary.txt'), 'w', encoding='utf-8') as f:
        f.write(f'Vocabulary Diversity (%): {word_diversity}\n')
        f.write('Coverage Scores (Top %):\n')
        for k, v in coverage_scores.items():
            f.write(f'  Top {k}%: {v}\n')

    draw_vocab_diversity_histogram(save_path, item_vs_pct, top_n)

    print(f'Vocabulary Diversity (%) = {word_diversity}')
    for k, v in coverage_scores.items():
        print(f'  Top {k}%: {v}')
    print('\n<SUCCESS>')
