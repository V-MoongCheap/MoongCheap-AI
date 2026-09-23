"""Summarize ambiguous catalog Facet mappings without choosing a value.

The output identifies repeated conflict patterns and textual overlap between
taxonomy values. It is a Human Review aid: it never changes a product mapping
or collapses two Facet values automatically.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd


REQUIRED_COLUMNS = {
    "catalog_id",
    "category_id",
    "facet_name",
    "mapping_status",
    "candidate_evidence",
}


def _normalise(value: object) -> str:
    return re.sub(r"\s+", "", str(value)).casefold()


def _evidence(value: object) -> list[dict[str, Any]]:
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError as error:
        raise ValueError("candidate_evidence must be a JSON array") from error
    if not isinstance(parsed, list) or not all(isinstance(item, dict) for item in parsed):
        raise ValueError("candidate_evidence must be a JSON array of objects")
    if len(parsed) < 2:
        raise ValueError("AMBIGUOUS mapping requires at least two candidates")
    return parsed


def _value_key(item: dict[str, Any]) -> tuple[int, str]:
    code = item.get("value_code")
    value = str(item.get("value", "")).strip()
    if value == "":
        raise ValueError("candidate evidence value is required")
    try:
        return int(code), value
    except (TypeError, ValueError) as error:
        raise ValueError("candidate evidence value_code must be an integer") from error


def _overlap_pairs(candidates: list[dict[str, Any]]) -> list[str]:
    values = [_value_key(item) for item in candidates]
    pairs = []
    for left_index, (_, left) in enumerate(values):
        normal_left = _normalise(left)
        for _, right in values[left_index + 1:]:
            normal_right = _normalise(right)
            if left != right and normal_left == normal_right:
                pairs.append(f"{left} = {right} (normalized duplicate)")
            elif normal_left != normal_right and normal_left in normal_right:
                pairs.append(f"{left} -> {right}")
            elif normal_left != normal_right and normal_right in normal_left:
                pairs.append(f"{right} -> {left}")
    return sorted(set(pairs))


def analyze(mapping: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, int]]:
    if missing := sorted(REQUIRED_COLUMNS - set(mapping.columns)):
        raise ValueError("mapping is missing columns: " + ", ".join(missing))
    grouped: dict[tuple[str, str, tuple[tuple[int, str], ...]], dict[str, Any]] = {}
    ambiguous = mapping.loc[mapping["mapping_status"].eq("AMBIGUOUS")].copy()
    for row in ambiguous.to_dict(orient="records"):
        candidates = _evidence(row["candidate_evidence"])
        values = tuple(sorted(_value_key(item) for item in candidates))
        key = (str(row["category_id"]), str(row["facet_name"]), values)
        item = grouped.setdefault(
            key,
            {
                "category_id": key[0],
                "facet_name": key[1],
                "candidate_values": json.dumps(
                    [{"code": code, "value": value} for code, value in values],
                    ensure_ascii=False,
                ),
                "catalog_count": 0,
                "sample_catalog_ids": [],
                "source_field_patterns": defaultdict(int),
                "textual_overlap_pairs": _overlap_pairs(candidates),
            },
        )
        item["catalog_count"] += 1
        if len(item["sample_catalog_ids"]) < 5:
            item["sample_catalog_ids"].append(str(row["catalog_id"]))
        fields = sorted(
            {
                field
                for candidate in candidates
                for field in candidate.get("source_fields", [])
                if str(field).strip()
            }
        )
        item["source_field_patterns"]["|".join(fields) or "NO_SOURCE_FIELD"] += 1

    rows = []
    for item in grouped.values():
        rows.append(
            {
                "category_id": item["category_id"],
                "facet_name": item["facet_name"],
                "candidate_values": item["candidate_values"],
                "catalog_count": item["catalog_count"],
                "sample_catalog_ids": json.dumps(item["sample_catalog_ids"], ensure_ascii=False),
                "source_field_patterns": json.dumps(
                    dict(sorted(item["source_field_patterns"].items())), ensure_ascii=False
                ),
                "textual_overlap_pairs": json.dumps(item["textual_overlap_pairs"], ensure_ascii=False),
                "taxonomy_overlap_review": bool(item["textual_overlap_pairs"]),
                "review_decision": "",
                "review_note": "",
            }
        )
    patterns = pd.DataFrame(rows)
    if patterns.empty:
        patterns = pd.DataFrame(
            columns=[
                "category_id", "facet_name", "candidate_values", "catalog_count",
                "sample_catalog_ids", "source_field_patterns", "textual_overlap_pairs",
                "taxonomy_overlap_review", "review_decision", "review_note",
            ]
        )
    else:
        patterns = patterns.sort_values(
            ["catalog_count", "category_id", "facet_name"], ascending=[False, True, True]
        ).reset_index(drop=True)
    overlap = patterns.loc[patterns["taxonomy_overlap_review"]].copy()
    summary = {
        "ambiguous_mapping_rows": int(len(ambiguous)),
        "ambiguity_patterns": int(len(patterns)),
        "taxonomy_overlap_patterns": int(len(overlap)),
        "taxonomy_overlap_mapping_rows": int(overlap["catalog_count"].sum()) if not overlap.empty else 0,
    }
    return patterns, overlap, summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze ambiguous product Facet mappings")
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--patterns-output", type=Path, required=True)
    parser.add_argument("--overlap-output", type=Path, required=True)
    parser.add_argument("--summary-output", type=Path, required=True)
    args = parser.parse_args()
    mapping = pd.read_csv(args.mapping, dtype=str, encoding="utf-8-sig").fillna("")
    patterns, overlap, summary = analyze(mapping)
    for path in (args.patterns_output, args.overlap_output, args.summary_output):
        path.parent.mkdir(parents=True, exist_ok=True)
    patterns.to_csv(args.patterns_output, index=False, encoding="utf-8-sig")
    overlap.to_csv(args.overlap_output, index=False, encoding="utf-8-sig")
    args.summary_output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
