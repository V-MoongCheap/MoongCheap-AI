from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from moongcheap_ai.health_foundation import build_health_artifacts


def main() -> None:
    parser = argparse.ArgumentParser(description="Build reviewable health category/catalog/facet candidates from MFDS facts")
    parser.add_argument("--input", type=Path, default=Path("data/interim/facet_discovery/i0030_products_clean_dedup.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed/health_foundation"))
    args = parser.parse_args()
    if not args.input.exists():
        raise SystemExit(f"input corpus not found: {args.input}")
    frame = pd.read_csv(args.input, dtype=str).fillna("")
    print(build_health_artifacts(frame, args.output_dir))


if __name__ == "__main__":
    main()
