from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from moongcheap_ai.data_foundation.labeling import label_demands, load_taxonomy


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch label synthetic or Backend-exported Demand with Facet Taxonomy V0")
    parser.add_argument("--input", type=Path, default=Path("data/synthetic/demands/synthetic_demands_v0.csv"))
    parser.add_argument("--taxonomy", type=Path, default=Path("data/processed/facet_discovery/facet_taxonomy_v0.json"))
    parser.add_argument("--output", type=Path, default=Path("data/processed/demands/demand_labeled_v0.csv"))
    parser.add_argument("--catalog", type=Path, help="Backend product_catalog export with id and category_id")
    parser.add_argument("--review-output", type=Path, default=Path("data/processed/demands/demand_label_review_queue_v0.csv"))
    parser.add_argument("--failure-output", type=Path, default=Path("data/processed/demands/labeling_failures_v0.csv"))
    parser.add_argument("--matching-output", type=Path, default=Path("data/processed/demands/facet_matching_report_v0.csv"))
    args = parser.parse_args()
    if not args.input.exists():
        raise SystemExit(f"input demand file not found: {args.input}")
    demands = pd.read_csv(args.input, dtype=str)
    if "processed_at" in demands.columns:
        processed = demands["processed_at"].fillna("").astype(str).str.strip()
        demands = demands[processed == ""].copy()
    catalog_map = None
    if args.catalog:
        if not args.catalog.exists():
            raise SystemExit(f"catalog export not found: {args.catalog}")
        catalog = pd.read_parquet(args.catalog) if args.catalog.suffix.lower() == ".parquet" else pd.read_csv(args.catalog, dtype=str)
        id_column = "id" if "id" in catalog.columns else "catalog_seed_id" if "catalog_seed_id" in catalog.columns else None
        if not id_column or "category_id" not in catalog.columns:
            raise SystemExit("catalog export must contain id (or catalog_seed_id) and Backend category_id")
        catalog_map = dict(zip(catalog[id_column].astype(str), catalog["category_id"].astype(str)))
    loader = load_taxonomy(args.taxonomy)
    result = label_demands(demands.fillna(""), loader, catalog_map)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output, index=False, encoding="utf-8-sig")
    matching_rows = []
    for facet in sorted(loader.category("").get("facets", []) if loader.category("") else [], key=lambda item: int(item.get("order", 0))):
        name = str(facet["name"])
        values = result["facet_values"].map(lambda value: json.loads(value).get(name, {}))
        matched = int(values.map(lambda value: int(value.get("code", 0)) != 0).sum())
        all_count = int(len(values) - matched)
        unresolved = int(result["unresolved_items"].map(lambda value: value not in ("", "[]")).sum())
        matching_rows.append({"facet_id": facet.get("facet_id", ""), "facet_name": name, "total": len(result), "matched": matched, "all_count": all_count, "unresolved": unresolved, "match_rate": matched / len(result) if len(result) else 0, "unresolved_rate": unresolved / len(result) if len(result) else 0})
    args.matching_output.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(matching_rows).to_csv(args.matching_output, index=False, encoding="utf-8-sig")
    review = result[result["label_status"] != "LABELED"].copy()
    args.review_output.parent.mkdir(parents=True, exist_ok=True)
    review.to_csv(args.review_output, index=False, encoding="utf-8-sig")
    failures = review.copy()
    failures["expected"] = ""
    failures["actual_result"] = failures["facet_values"]
    failures["actual"] = failures["actual_result"]
    failures["category_id"] = failures.get("category_id", "")
    failures["taxonomy_version"] = "v0-draft"
    failures["facet_id"] = ""
    failures["matched_alias"] = ""
    failures["failure_type"] = failures["label_warnings"].map(
        lambda value: "taxonomy_missing" if "did not match" in str(value) else "ambiguous_expression"
    )
    failures["note"] = failures["label_warnings"]
    failure_columns = ["demand_id", "catalog_id", "category_id", "taxonomy_version", "extra_requirement", "expected", "actual", "actual_result", "facet_id", "matched_alias", "failure_type", "unresolved_items", "note"]
    args.failure_output.parent.mkdir(parents=True, exist_ok=True)
    failures.reindex(columns=failure_columns).to_csv(args.failure_output, index=False, encoding="utf-8-sig")
    print({"rows": len(result), "review_rows": len(review), "failure_rows": len(failures), "output": str(args.output), "review_output": str(args.review_output), "failure_output": str(args.failure_output), "matching_output": str(args.matching_output)})


if __name__ == "__main__":
    main()
