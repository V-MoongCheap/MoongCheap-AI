"""Lightweight product-name retrieval benchmark for the AI-Hub staging data.

This is deliberately dependency-light.  Barcode duplicate groups are used only
as an observed identity proxy; they are not treated as a verified gold label.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Callable

import pandas as pd


TOKEN_RE = re.compile(r"[가-힣A-Za-z0-9]+")


def _tokens(text: str) -> list[str]:
    return TOKEN_RE.findall(str(text or "").lower())


def _char_ngrams(text: str, min_n: int = 2, max_n: int = 4) -> list[str]:
    value = re.sub(r"\s+", "", str(text or "").lower())
    return [value[i : i + n] for n in range(min_n, max_n + 1) for i in range(max(0, len(value) - n + 1))]


class SparseTfidf:
    def __init__(self, documents: list[list[str]]) -> None:
        document_frequency = Counter()
        for terms in documents:
            document_frequency.update(set(terms))
        count = max(1, len(documents))
        self.idf = {
            term: math.log((1 + count) / (1 + frequency)) + 1.0
            for term, frequency in document_frequency.items()
        }

    def vector(self, terms: list[str]) -> dict[str, float]:
        counts = Counter(term for term in terms if term in self.idf)
        vector = {term: frequency * self.idf[term] for term, frequency in counts.items()}
        norm = math.sqrt(sum(value * value for value in vector.values()))
        return {term: value / norm for term, value in vector.items()} if norm else {}


def _cosine(left: dict[str, float], right: dict[str, float]) -> float:
    if len(left) > len(right):
        left, right = right, left
    return sum(value * right.get(term, 0.0) for term, value in left.items())


def _stable_bucket(value: str) -> int:
    return int(hashlib.sha1(value.encode("utf-8")).hexdigest()[:8], 16) % 10


def _candidate_rows(frame: pd.DataFrame, train: bool) -> tuple[list[tuple[int, int, list[int]]], int]:
    grouped = frame.groupby("barcode", sort=True).indices
    threshold = 8 if train else 0
    groups = [
        list(indices)
        for barcode, indices in grouped.items()
        if str(barcode)
        and len(indices) >= 2
        and ((_stable_bucket(str(barcode)) >= threshold) if train else (_stable_bucket(str(barcode)) < 8))
    ]
    kan_index: defaultdict[str, list[int]] = defaultdict(list)
    for index, kan_code in enumerate(frame["kan_code"]):
        kan_index[kan_code].append(index)
    queries: list[tuple[int, int, list[int]]] = []
    for indices in groups:
        anchor, positive = indices[0], indices[1]
        group_set = set(indices)
        negatives = [idx for idx in kan_index[frame.iloc[anchor]["kan_code"]] if idx not in group_set]
        negatives = negatives[:20]
        if negatives:
            queries.append((anchor, positive, negatives))
    return queries, len(groups)


def _evaluate(
    queries: list[tuple[int, int, list[int]]],
    score: Callable[[int, int], float],
) -> dict[str, float | int]:
    ranks: list[int] = []
    for query, positive, negatives in queries:
        ranked = sorted([(score(query, positive), positive)] + [(score(query, idx), idx) for idx in negatives], reverse=True)
        rank = next(position for position, (_, index) in enumerate(ranked, 1) if index == positive)
        ranks.append(rank)
    if not ranks:
        return {"queries": 0, "recall_at_1": 0.0, "recall_at_5": 0.0, "recall_at_10": 0.0, "mrr": 0.0}
    return {
        "queries": len(ranks),
        "recall_at_1": sum(rank <= 1 for rank in ranks) / len(ranks),
        "recall_at_5": sum(rank <= 5 for rank in ranks) / len(ranks),
        "recall_at_10": sum(rank <= 10 for rank in ranks) / len(ranks),
        "mrr": sum(1.0 / rank for rank in ranks) / len(ranks),
    }


def run_benchmark(staging: pd.DataFrame, max_rows: int = 50000) -> tuple[pd.DataFrame, dict]:
    """Evaluate four deterministic name-matching baselines on held-out barcode groups."""
    required = {"barcode", "product_name_normalized", "kan_code"}
    missing = required - set(staging.columns)
    if missing:
        raise ValueError(f"missing benchmark columns: {sorted(missing)}")
    frame = staging.copy()
    frame["barcode"] = frame["barcode"].fillna("").astype(str)
    frame["product_name_normalized"] = frame["product_name_normalized"].fillna("").astype(str)
    frame["kan_code"] = frame["kan_code"].fillna("").astype(str)
    duplicate_barcodes = frame.groupby("barcode").size()
    eligible = frame[frame["barcode"].isin(duplicate_barcodes[duplicate_barcodes >= 2].index)].copy()
    if len(eligible) > max_rows:
        eligible = eligible.sort_values(["barcode", "source_file", "source_row"]).head(max_rows)
    eligible = eligible.reset_index(drop=True)
    train_queries, train_groups = _candidate_rows(eligible, train=True)
    test_queries, test_groups = _candidate_rows(eligible, train=False)

    names = eligible["product_name_normalized"].tolist()
    word_terms = [_tokens(name) for name in names]
    char_terms = [_char_ngrams(name) for name in names]
    word_model = SparseTfidf(word_terms)
    char_model = SparseTfidf(char_terms)
    word_vectors = [word_model.vector(terms) for terms in word_terms]
    char_vectors = [char_model.vector(terms) for terms in char_terms]

    exact = lambda left, right: float(names[left] == names[right] and bool(names[left]))
    word = lambda left, right: _cosine(word_vectors[left], word_vectors[right])
    char = lambda left, right: _cosine(char_vectors[left], char_vectors[right])
    hybrid = lambda left, right: 0.5 * word(left, right) + 0.5 * char(left, right)
    models = [("exact_normalized_name", exact), ("word_tfidf", word), ("char_tfidf_2_4gram", char), ("hybrid_word_char", hybrid)]

    rows = []
    for model_name, scorer in models:
        metrics = _evaluate(test_queries, scorer)
        rows.append({"model": model_name, **metrics})
    result = pd.DataFrame(rows)
    winner = result.sort_values(["mrr", "recall_at_1", "recall_at_5"], ascending=False).iloc[0]["model"] if not result.empty else None
    report = {
        "status": "COMPLETED" if test_queries else "SKIPPED_NO_ELIGIBLE_PAIRS",
        "evaluation_type": "barcode_duplicate_proxy_retrieval",
        "warning": "Barcode duplicate groups are an observed identity proxy, not a verified gold label.",
        "eligible_rows": len(eligible),
        "train_duplicate_groups": train_groups,
        "test_duplicate_groups": test_groups,
        "test_queries": len(test_queries),
        "candidate_negative_policy": "up to 20 same-KAN rows outside the query barcode group",
        "selected_model": winner,
    }
    return result, report


def write_benchmark_outputs(staging_path: Path, output_dir: Path, max_rows: int = 50000) -> dict:
    staging = pd.read_parquet(staging_path)
    metrics, report = run_benchmark(staging, max_rows=max_rows)
    output_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = output_dir / "aihub_model_comparison.csv"
    report_path = output_dir / "aihub_model_benchmark.json"
    metrics.to_csv(metrics_path, index=False, encoding="utf-8-sig")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"metrics": str(metrics_path), "report": str(report_path), **report}
