from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from moongcheap_ai.downstream_v21 import run_downstream_v21


def main() -> None:
    parser = argparse.ArgumentParser(description="Run database-free V2.1 downstream pipeline")
    parser.add_argument("--input", type=Path, default=Path("data/interim/facet_discovery/i0030_products_clean_dedup.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed/downstream_v2_1"))
    parser.add_argument("--count", type=int, default=32)
    args = parser.parse_args()
    if not args.input.exists():
        raise SystemExit(f"input corpus not found: {args.input}")
    print(run_downstream_v21(pd.read_csv(args.input, dtype=str).fillna(""), args.output_dir, args.count))


if __name__ == "__main__":
    main()
