from __future__ import annotations

import argparse
from pathlib import Path

from moongcheap_ai.data_foundation.demand_synthetic import generate_from_catalog_file


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate clearly marked synthetic Demand input rows")
    parser.add_argument("--catalog", type=Path, default=Path("data/processed/product_catalog/product_catalog_health_food_subset_v0.parquet"))
    parser.add_argument("--taxonomy", type=Path)
    parser.add_argument("--output", type=Path, default=Path("data/synthetic/demands/synthetic_demands_v0.csv"))
    parser.add_argument("--count", type=int, default=30)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if not args.catalog.exists():
        raise SystemExit(f"catalog not found: {args.catalog}")
    print(generate_from_catalog_file(args.catalog, args.output, args.count, args.seed, args.taxonomy))


if __name__ == "__main__":
    main()
