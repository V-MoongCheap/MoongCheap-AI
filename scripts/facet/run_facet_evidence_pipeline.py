from __future__ import annotations

import argparse
from pathlib import Path

from moongcheap_ai.data_foundation.facet_evidence import run_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Build provenance-preserving Facet evidence from local source snapshots")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, default=Path("data/interim/facet_discovery"))
    parser.add_argument("--enable-amazon-reviews", action="store_true")
    parser.add_argument("--max-reviews-per-product", type=int, default=None, help="Cap Model 1 evidence rows per product while preserving raw snapshots")
    args = parser.parse_args()
    print(run_pipeline(args.root, args.output_dir, enable_reviews=args.enable_amazon_reviews, max_reviews_per_product=args.max_reviews_per_product))


if __name__ == "__main__":
    main()
