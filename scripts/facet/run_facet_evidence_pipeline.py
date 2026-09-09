from __future__ import annotations

import argparse
from pathlib import Path

from moongcheap_ai.data_foundation.facet_evidence import run_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Build provenance-preserving Facet evidence from local source snapshots")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, default=Path("data/interim/facet_evidence"))
    parser.add_argument("--enable-amazon-reviews", action="store_true")
    args = parser.parse_args()
    print(run_pipeline(args.root, args.output_dir, enable_reviews=args.enable_amazon_reviews))


if __name__ == "__main__":
    main()
