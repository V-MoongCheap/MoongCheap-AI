"""Independent-generation majority vote shared by Model 1 experiments."""

from collections import Counter
import json

import pandas as pd


def gate_observed_candidates(frame: pd.DataFrame, sources: list[dict]) -> pd.DataFrame:
    """Only real-source evidence may support a value, never a verifier draft."""
    if frame.empty:
        return frame.copy()
    excluded = {
        "source_product_id",
        "source_type",
        "category_key",
        "category_name",
        "category_path",
        "source_category_path",
        "manufacturer",
        "brand",
        "seller_id",
    }
    by_id: dict[str, list[str]] = {}
    for source in sources:
        by_id.setdefault(str(source.get("source_product_id", "")), []).extend(
            str(value) for key, value in source.items() if key not in excluded
        )

    def valid(row):
        text = str(row.get("source_text", "")).strip()
        value = str(row.get("value", "")).strip()
        return (
            bool(text and value)
            and value.casefold() in text.casefold()
            and any(
                text in original
                for original in by_id.get(str(row.get("source_product_id", "")), [])
            )
        )

    return frame.loc[[valid(row) for row in frame.to_dict("records")]].copy()


def select_consensus(frames: list[pd.DataFrame], total_attempts: int) -> pd.DataFrame:
    """One vote per candidate per generation; failed generations still count."""
    if total_attempts < 1 or len(frames) > total_attempts:
        raise ValueError("invalid generation count")
    votes: Counter[tuple[str, str]] = Counter()
    for frame in frames:
        votes.update(
            {
                (
                    str(row.get("name", "")).strip().casefold(),
                    str(row.get("value", "")).strip().casefold(),
                )
                for row in frame.to_dict("records")
            }
        )
    accepted = {
        key
        for key, count in votes.items()
        if all(key) and count >= total_attempts // 2 + 1
    }
    rows = [
        row
        for frame in frames
        for row in frame.to_dict("records")
        if (
            str(row.get("name", "")).strip().casefold(),
            str(row.get("value", "")).strip().casefold(),
        )
        in accepted
    ]
    if not rows:
        return frames[0].iloc[:0].copy() if frames else pd.DataFrame()
    # Model output may retain structured aliases/evidence. pandas' hash-based
    # drop_duplicates rejects list/dict cells even when consensus is valid.
    unique = []
    seen = set()
    for row in rows:
        fingerprint = json.dumps(row, sort_keys=True, ensure_ascii=False, default=str)
        if fingerprint not in seen:
            seen.add(fingerprint)
            unique.append(row)
    return pd.DataFrame(unique).reset_index(drop=True)
