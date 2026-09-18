"""Build final draft artifacts from the human-reviewed Model 1 queue."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

try:
    from scripts.model1.build_approved_taxonomy_and_mapping import (
        build_product_mapping,
        build_taxonomy,
    )
except ModuleNotFoundError:  # direct execution: python scripts/model1/<file>.py
    from build_approved_taxonomy_and_mapping import build_product_mapping, build_taxonomy


def human_approved_candidates(review: pd.DataFrame) -> pd.DataFrame:
    """Convert human decisions into the candidate contract used downstream."""
    rows: list[dict[str, str]] = []
    for _, row in review.fillna("").iterrows():
        decision = str(row.get("human_review_decision", "")).strip().upper()
        if decision == "APPROVE":
            values = [str(row.get("value_candidate", "")).strip()]
        elif decision == "EDIT":
            raw_values = str(row.get("human_corrected_values_json", "")).strip()
            try:
                values = json.loads(raw_values)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid human correction JSON for {row.get('review_id')}") from exc
            if not isinstance(values, list) or not all(isinstance(value, str) and value.strip() for value in values):
                raise ValueError(f"human correction must be a non-empty string list for {row.get('review_id')}")
        else:
            continue
        facet = str(row.get("human_corrected_facet", "")).strip() or str(row.get("facet_candidate", "")).strip()
        for value in values:
            value = value.strip()
            if not facet or not value:
                continue
            rows.append(
                {
                    "category_key": str(row.get("category_id", "")).strip(),
                    "facet_name": facet,
                    "value": value,
                    "review_id": str(row.get("review_id", "")).strip(),
                    "human_review_decision": decision,
                    "human_approved": "True",
                }
            )
    result = pd.DataFrame(rows)
    if result.empty:
        return pd.DataFrame(columns=["category_key", "facet_name", "value", "review_id", "human_review_decision", "human_approved"])
    return result.drop_duplicates(["category_key", "facet_name", "value"]).sort_values(
        ["category_key", "facet_name", "value"]
    ).reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--human-review", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--products", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    review = pd.read_csv(args.human_review, dtype=str, encoding="utf-8-sig").fillna("")
    inputs = pd.read_json(args.input, lines=True).fillna("")
    products = pd.read_csv(args.products, dtype=str).fillna("")
    candidates = human_approved_candidates(review)
    names = dict(inputs[["category_key", "category_name"]].drop_duplicates("category_key").itertuples(index=False, name=None))
    taxonomy = build_taxonomy(candidates, names)
    taxonomy["status"] = "HUMAN_REVIEWED_DRAFT"
    taxonomy["version"] = "model1-human-reviewed-v1"
    taxonomy["taxonomy_version"] = "model1-human-reviewed-v1"
    taxonomy["approval_status"] = "HUMAN_REVIEWED_PENDING_BACKEND_ID_MAPPING"
    taxonomy["human_approved"] = True
    taxonomy["source"] = "HUMAN_REVIEWED_MODEL1_CANDIDATES"
    for category in taxonomy["categories"]:
        category["status"] = "HUMAN_REVIEWED_DRAFT"
        category["approval_status"] = "HUMAN_REVIEWED_PENDING_BACKEND_ID_MAPPING"
        category["human_approved"] = True

    mapping = build_product_mapping(products, taxonomy)
    (args.output_dir / "facet_taxonomy_v0_human_reviewed.json").write_text(
        json.dumps(taxonomy, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    candidates.to_csv(args.output_dir / "facet_candidates_human_approved.csv", index=False, encoding="utf-8-sig")
    mapping.to_csv(args.output_dir / "product_facet_mapping_human_reviewed.csv", index=False, encoding="utf-8-sig")
    summary = {
        "review_rows": len(review),
        "human_approved_unique_candidates": len(candidates),
        "categories": len(taxonomy["categories"]),
        "facets": sum(len(category["facets"]) for category in taxonomy["categories"]),
        "values_without_all": sum(len(facet["values"]) - 1 for category in taxonomy["categories"] for facet in category["facets"]),
        "mapping_rows": len(mapping),
        "mapped_rows": int(mapping["mapping_status"].eq("MAPPED").sum()) if not mapping.empty else 0,
        "unmapped_rows": int(mapping["mapping_status"].eq("UNMAPPED").sum()) if not mapping.empty else 0,
        "all_code_zero": all(facet["values"][0]["code"] == 0 for category in taxonomy["categories"] for facet in category["facets"]),
    }
    (args.output_dir / "human_reviewed_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
