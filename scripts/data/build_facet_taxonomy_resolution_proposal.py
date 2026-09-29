"""Build a conservative proposal for resolving Facet taxonomy overlaps.

Only whitespace/case-normalised duplicates are proposed as alias merges. Any
semantic containment or product-vs-ingredient relationship remains pending
human review and does not receive a canonical code.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pandas as pd


def _normalise(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def _parse_values(raw: object) -> list[dict[str, object]]:
    values = json.loads(str(raw))
    if not isinstance(values, list):
        raise ValueError("candidate_values must be a JSON array")
    return values


def build_proposal(overlap: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    required = {"category_id", "facet_name", "candidate_values", "catalog_count", "textual_overlap_pairs"}
    missing = sorted(required - set(overlap.columns))
    if missing:
        raise ValueError("overlap file is missing columns: " + ", ".join(missing))

    rows: list[dict[str, object]] = []
    for source in overlap.to_dict(orient="records"):
        values = _parse_values(source["candidate_values"])
        duplicate_groups: dict[str, list[dict[str, object]]] = {}
        for value in values:
            text = str(value.get("value", "")).strip()
            duplicate_groups.setdefault(_normalise(text), []).append(value)
        duplicates = [group for group in duplicate_groups.values() if len(group) > 1]
        has_non_duplicate_overlap = any(
            "normalized duplicate" not in str(pair)
            for pair in json.loads(str(source["textual_overlap_pairs"]))
        )

        if len(duplicates) == 1 and not has_non_duplicate_overlap:
            group = sorted(duplicates[0], key=lambda item: (int(item["code"]), str(item["value"])))
            canonical = group[0]
            aliases = [str(item["value"]) for item in group[1:]]
            resolution_type = "MERGE_AS_ALIAS_CANDIDATE"
            canonical_code: object = canonical["code"]
            canonical_value: object = canonical["value"]
            rationale = "Normalized duplicate display values; preserve the lowest existing code and move other spellings to aliases."
        else:
            aliases = []
            resolution_type = "SEMANTIC_REVIEW_REQUIRED"
            canonical_code = ""
            canonical_value = ""
            rationale = "Values overlap textually but may represent different ingredients, product forms, or specificity levels; do not merge automatically."

        rows.append(
            {
                "category_id": source["category_id"],
                "facet_name": source["facet_name"],
                "candidate_values": source["candidate_values"],
                "catalog_count": source["catalog_count"],
                "resolution_type": resolution_type,
                "proposed_canonical_code": canonical_code,
                "proposed_canonical_value": canonical_value,
                "proposed_aliases": json.dumps(aliases, ensure_ascii=False),
                "review_decision": "PENDING_HUMAN_REVIEW",
                "review_note": rationale,
            }
        )

    result = pd.DataFrame(rows)
    if not result.empty:
        result = result.sort_values(
            ["resolution_type", "catalog_count", "category_id", "facet_name"],
            ascending=[True, False, True, True],
        ).reset_index(drop=True)
    summary = {
        "overlap_patterns": int(len(result)),
        "alias_merge_candidates": int((result["resolution_type"] == "MERGE_AS_ALIAS_CANDIDATE").sum()) if not result.empty else 0,
        "semantic_review_required": int((result["resolution_type"] == "SEMANTIC_REVIEW_REQUIRED").sum()) if not result.empty else 0,
        "review_status": "PENDING_HUMAN_REVIEW",
    }
    return result, summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Build conservative Facet taxonomy resolution proposals")
    parser.add_argument("--overlap", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary-output", type=Path, required=True)
    args = parser.parse_args()
    overlap = pd.read_csv(args.overlap, dtype=str, encoding="utf-8-sig").fillna("")
    proposal, summary = build_proposal(overlap)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    proposal.to_csv(args.output, index=False, encoding="utf-8-sig")
    args.summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
