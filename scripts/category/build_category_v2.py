from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from moongcheap_ai.category_v2 import build_category_v2


def main() -> None:
    parser = argparse.ArgumentParser(description="Build hierarchical service category candidates from MFDS facts")
    parser.add_argument("--input", type=Path, default=Path("data/interim/facet_discovery/i0030_products_clean_dedup.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed/category_v2"))
    args = parser.parse_args()
    if not args.input.exists():
        raise SystemExit(f"input corpus not found: {args.input}")
    print(build_category_v2(pd.read_csv(args.input, dtype=str).fillna(""), args.output_dir))


if __name__ == "__main__":
    main()
