from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from moongcheap_ai.data_foundation.category_v2_1 import build_category_v2_1


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply approved V2.1 category candidates without changing facets")
    parser.add_argument("--input", type=Path, default=Path("data/interim/facet_discovery/i0030_products_clean_dedup.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed/category_v2_1"))
    args = parser.parse_args()
    if not args.input.exists():
        raise SystemExit(f"input corpus not found: {args.input}")
    print(build_category_v2_1(pd.read_csv(args.input, dtype=str).fillna(""), args.output_dir))


if __name__ == "__main__":
    main()
