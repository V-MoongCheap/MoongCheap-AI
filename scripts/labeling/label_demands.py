from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from moongcheap_ai.labeling import label_demands, load_taxonomy


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch label synthetic or Backend-exported Demand with Facet Taxonomy V0")
    parser.add_argument("--input", type=Path, default=Path("data/interim/demands/synthetic_demands_v0.csv"))
    parser.add_argument("--taxonomy", type=Path, default=Path("data/processed/facet_discovery/facet_taxonomy_v0.json"))
    parser.add_argument("--output", type=Path, default=Path("data/processed/demands/demand_labeled_v0.csv"))
    parser.add_argument("--catalog", type=Path, help="Backend product_catalog export with id and category_id")
    parser.add_argument("--review-output", type=Path, default=Path("data/processed/demands/demand_label_review_queue_v0.csv"))
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
    result = label_demands(demands.fillna(""), load_taxonomy(args.taxonomy), catalog_map)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output, index=False, encoding="utf-8-sig")
    review = result[result["label_status"] != "LABELED"].copy()
    args.review_output.parent.mkdir(parents=True, exist_ok=True)
    review.to_csv(args.review_output, index=False, encoding="utf-8-sig")
    print({"rows": len(result), "review_rows": len(review), "output": str(args.output), "review_output": str(args.review_output)})


if __name__ == "__main__":
    main()
