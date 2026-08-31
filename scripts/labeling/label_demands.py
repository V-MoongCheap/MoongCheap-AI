from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from moongcheap_ai.labeling import label_demands, load_taxonomy


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch label Mock Demand with Facet Taxonomy V0")
    parser.add_argument("--input", type=Path, default=Path("data/interim/demands/mock_demands_v0.csv"))
    parser.add_argument("--taxonomy", type=Path, default=Path("data/processed/facet_discovery/aihub_exploratory_facet_taxonomy_v0.json"))
    parser.add_argument("--output", type=Path, default=Path("data/processed/demands/demand_labeled_v0.csv"))
    args = parser.parse_args()
    if not args.input.exists():
        raise SystemExit(f"input demand file not found: {args.input}")
    demands = pd.read_csv(args.input, dtype=str)
    if "processed_at" in demands.columns:
        processed = demands["processed_at"].fillna("").astype(str).str.strip()
        demands = demands[processed == ""].copy()
    result = label_demands(demands.fillna(""), load_taxonomy(args.taxonomy))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output, index=False, encoding="utf-8-sig")
    print({"rows": len(result), "output": str(args.output)})


if __name__ == "__main__":
    main()
