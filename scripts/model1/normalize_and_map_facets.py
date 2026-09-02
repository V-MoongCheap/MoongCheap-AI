from __future__ import annotations
import argparse
from pathlib import Path
import pandas as pd
from moongcheap_ai.data_foundation.model1_postprocess import map_products, normalize_candidates

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review", type=Path, default=Path("data/processed/model1_v0/facet_discovery_model_review_v0.csv"))
    parser.add_argument("--input", type=Path, default=Path("data/interim/facet_discovery/i0030_products_clean_dedup.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed/model1_v0"))
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    candidates = normalize_candidates(pd.read_csv(args.review, dtype=str).fillna(""))
    mapping = map_products(pd.read_csv(args.input, dtype=str).fillna(""), candidates)
    candidates.to_csv(args.output_dir / "facet_candidates_normalized_v0.csv", index=False, encoding="utf-8-sig")
    mapping.to_csv(args.output_dir / "product_facet_mapping_v0.csv", index=False, encoding="utf-8-sig")
    print({"candidate_count": len(candidates), "mapping_rows": len(mapping), "mapped_rows": int((mapping.mapping_status == "MAPPED").sum()) if not mapping.empty else 0, "unmapped_rows": int((mapping.mapping_status == "UNMAPPED").sum()) if not mapping.empty else 0})

if __name__ == "__main__":
    main()
