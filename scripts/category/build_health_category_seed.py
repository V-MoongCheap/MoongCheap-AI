from __future__ import annotations

import argparse
from pathlib import Path

from moongcheap_ai.category_seed import CategorySeedError, write_health_category_seed


def main() -> None:
    parser = argparse.ArgumentParser(description="Build ERD-shaped health category seed from MFDS data")
    parser.add_argument("--mfds", type=Path, default=Path("data/interim/facet_discovery/i0030_products_clean.parquet"))
    parser.add_argument("--output", type=Path, default=Path("data/processed/category/health_category_seed_v0.csv"))
    args = parser.parse_args()
    if not args.mfds.exists():
        raise SystemExit(f"MFDS source not found: {args.mfds}; category seed was not fabricated")
    try:
        print(write_health_category_seed(args.mfds, args.output))
    except CategorySeedError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
