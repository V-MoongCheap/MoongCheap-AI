"""Prepare a deduplicated, atomic-value Model 1 review queue.

This is a mechanical pre-review step. It expands obvious multi-value
expressions (comma/slash separated), preserves the original expression for
audit, and merges duplicate category/facet/value rows. It deliberately does
not split conjunctions such as an official compound ingredient name without
stronger evidence.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd


VALUE_COLUMN = "value_candidate"
ATOMIC_COLUMN = "atomic_value"
SOURCE_COLUMN = "composite_source_value"


def split_obvious_values(value: str) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    # Conjunctions are intentionally not split: they may form one official
    # name (for example, a compound ingredient). Human review should never be
    # asked to discover this distinction for comma/slash cases, which are the
    # common accidental aggregation pattern.
    parts = re.split(r"\s*[,，/]\s*", text)
    return [part.strip() for part in parts if part.strip()]


def prepare_queue(frame: pd.DataFrame) -> pd.DataFrame:
    if VALUE_COLUMN not in frame.columns:
        raise ValueError(f"missing required column: {VALUE_COLUMN}")
    rows: list[dict[str, str]] = []
    for _, row in frame.fillna("").iterrows():
        original = str(row[VALUE_COLUMN]).strip()
        parts = split_obvious_values(original)
        for part in parts or [original]:
            record = row.to_dict()
            record[VALUE_COLUMN] = part
            record[ATOMIC_COLUMN] = part
            record[SOURCE_COLUMN] = original if len(parts) > 1 else ""
            rows.append(record)
    expanded = pd.DataFrame(rows).fillna("")
    keys = [column for column in ("category_id", "category_key", "facet_candidate", "facet_name", ATOMIC_COLUMN) if column in expanded.columns]
    if not keys:
        raise ValueError("queue has no category/facet/value identity columns")

    # Preserve the strongest observed evidence and combine provenance instead
    # of presenting duplicate rows to the reviewer.
    support_values = expanded["support_count"] if "support_count" in expanded else pd.Series(0, index=expanded.index)
    ratio_values = expanded["document_ratio"] if "document_ratio" in expanded else pd.Series(0, index=expanded.index)
    expanded["_support_numeric"] = pd.to_numeric(support_values, errors="coerce").fillna(0)
    expanded["_ratio_numeric"] = pd.to_numeric(ratio_values, errors="coerce").fillna(0)
    rows = []
    for _, group in expanded.groupby(keys, sort=True, dropna=False):
        first = group.iloc[0].copy()
        if "support_count" in first:
            first["support_count"] = str(int(group["_support_numeric"].max()))
        if "document_ratio" in first:
            first["document_ratio"] = str(group["_ratio_numeric"].max())
        for column in ("aliases", "evidence_terms", "source_product_ids", "source_fields"):
            if column in group:
                values = sorted({str(value).strip() for value in group[column] if str(value).strip()})
                first[column] = " | ".join(values)
        rows.append(first.drop(labels=["_support_numeric", "_ratio_numeric"]))
    result = pd.DataFrame(rows).reset_index(drop=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    frame = pd.read_csv(args.input, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    result = prepare_queue(frame)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output, index=False, encoding="utf-8-sig")
    print({"input_rows": len(frame), "output_rows": len(result), "output": str(args.output)})


if __name__ == "__main__":
    main()
