"""Build a Model 1 Facet Discovery Gold Set from a reviewed queue.

The input may be either the taxonomy review queue or the multisource review
queue used by earlier Model 1 experiments.  Only explicit APPROVE/ACCEPT/EDIT
decisions become Gold rows.  Pending, rejected, and uncertain rows are kept in
an audit export and never silently promoted.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd


APPROVED = {"APPROVE", "ACCEPT", "EDIT", "APPROVED"}
REJECTED = {"REJECT", "REJECTED", "EXCLUDE", "EXCLUDED"}
PENDING = {"", "PENDING", "PENDING_REVIEW", "REVIEW", "REVIEW_REQUIRED", "UNCERTAIN"}


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _parse_list(value: Any) -> list[str]:
    raw = _text(value)
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        try:
            parsed = ast.literal_eval(raw)
        except (ValueError, SyntaxError):
            parsed = [part.strip() for part in raw.split("|") if part.strip()]
    if isinstance(parsed, str):
        parsed = [parsed]
    if not isinstance(parsed, list):
        return []
    return [_text(item) for item in parsed if _text(item)]


def _decision(row: pd.Series) -> str:
    for column in ("human_decision", "human_review_decision", "review_decision"):
        value = _text(row.get(column, "")).upper()
        if value:
            return value
    return ""


def _category(row: pd.Series) -> str:
    return _text(row.get("category_key", row.get("category_id", "")))


def _facet(row: pd.Series) -> str:
    return _text(row.get("human_corrected_facet", "")) or _text(
        row.get("facet_candidate", row.get("facet_name", ""))
    )


def _values(row: pd.Series, decision: str) -> list[str]:
    if decision == "EDIT":
        for column in ("human_corrected_values_json", "corrected_values_json", "human_value"):
            values = _parse_list(row.get(column, ""))
            if values:
                return values
    for column in ("value_candidate", "facet_value", "value"):
        value = _text(row.get(column, ""))
        if value:
            return [value]
    return []


def _aliases(row: pd.Series) -> list[str]:
    for column in ("human_aliases", "aliases"):
        values = _parse_list(row.get(column, ""))
        if values:
            return values
    return []


def _stable_split(key: str) -> str:
    # Stable row-level split; rerunning the script never changes partitions.
    bucket = int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:8], 16) % 100
    if bucket < 70:
        return "DEV"
    if bucket < 85:
        return "HOLDOUT"
    return "CHALLENGE"


def build_gold(review: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    gold_rows: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    for index, row in review.fillna("").iterrows():
        decision = _decision(row)
        category = _category(row)
        facet = _facet(row)
        values = _values(row, decision)
        reason = _text(row.get("human_note", "")) or _text(
            row.get("human_review_note", row.get("review_note", ""))
        )
        base = {
            "source_row": index + 1,
            "review_decision": decision,
            "category_key": category,
            "category_name": _text(row.get("category_name", "")),
            "facet_name": facet,
            "value_candidate": _text(row.get("value_candidate", row.get("facet_value", ""))),
            "human_note": reason,
        }
        if decision in APPROVED and category and facet and values:
            for value in values:
                key = f"{category}|{facet}|{value}"
                gold_rows.append(
                    {
                        **base,
                        "canonical_value": value,
                        "aliases": json.dumps(_aliases(row), ensure_ascii=False),
                        "support_count": _text(row.get("support_count", "")),
                        "document_ratio": _text(row.get("document_ratio", "")),
                        "source_fields": _text(row.get("source_fields", "")),
                        "evidence_terms": _text(row.get("evidence_terms", "")),
                        "evidence_product_ids": _text(row.get("source_product_ids", "")),
                        "split": _stable_split(key),
                        "gold_status": "GOLD_READY",
                    }
                )
        else:
            audit_rows.append(
                {
                    **base,
                    "values_found": json.dumps(values, ensure_ascii=False),
                    "resolution": (
                        "REJECTED_OR_EXCLUDED" if decision in REJECTED else "PENDING_OR_INVALID"
                    ),
                }
            )

    gold = pd.DataFrame(gold_rows)
    if not gold.empty:
        gold = gold.drop_duplicates(["category_key", "facet_name", "canonical_value"])
        gold = gold.sort_values(["split", "category_key", "facet_name", "canonical_value"]).reset_index(drop=True)
    audit = pd.DataFrame(audit_rows)
    return gold, audit


def build_outputs(input_path: Path, output_dir: Path) -> dict[str, Any]:
    review = pd.read_csv(input_path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    gold, audit = build_gold(review)
    output_dir.mkdir(parents=True, exist_ok=True)
    gold_path = output_dir / "facet_gold_set_v1.csv"
    audit_path = output_dir / "facet_gold_pending_excluded_v1.csv"
    summary_path = output_dir / "facet_gold_summary.json"
    gold.to_csv(gold_path, index=False, encoding="utf-8-sig")
    audit.to_csv(audit_path, index=False, encoding="utf-8-sig")
    summary = {
        "input_rows": len(review),
        "gold_rows_before_deduplication": int(len(gold)),
        "gold_rows": int(len(gold)),
        "audit_rows": int(len(audit)),
        "categories": int(gold["category_key"].nunique()) if not gold.empty else 0,
        "facets": int(gold[["category_key", "facet_name"]].drop_duplicates().shape[0]) if not gold.empty else 0,
        "split_counts": gold["split"].value_counts().to_dict() if not gold.empty else {},
        "gold_policy": "Only explicit APPROVE/ACCEPT/EDIT with a category, facet, and value are GOLD_READY.",
        "gold_path": str(gold_path),
        "audit_path": str(audit_path),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build_outputs(args.review, args.output_dir), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
