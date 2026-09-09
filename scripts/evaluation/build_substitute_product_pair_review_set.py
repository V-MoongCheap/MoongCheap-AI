from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from moongcheap_ai.demand_clustering.evaluation.substitute_review_set import (
    REVIEW_COLUMNS,
    build_substitute_product_pair_review_set,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build a directional MFDS product-pair set for offline human review"
        )
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path(
            "data/interim/facet_discovery/i0030_products_clean_dedup.csv"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "data/processed/substitute_product/pair_review_v1.csv"
        ),
    )
    parser.add_argument("--pairs-per-stratum", type=int, default=60)
    parser.add_argument("--seed", type=int, default=20260906)
    args = parser.parse_args()

    if not args.input.exists():
        raise SystemExit(
            "MFDS product corpus not found: "
            f"{args.input}. Provide the I0030 export or configure collection first."
        )
    frame = pd.read_csv(args.input, dtype=str).fillna("")
    rows, summary = build_substitute_product_pair_review_set(
        frame.to_dict("records"),
        directional_pairs_per_stratum=args.pairs_per_stratum,
        seed=args.seed,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=REVIEW_COLUMNS).to_csv(
        args.output,
        index=False,
        encoding="utf-8-sig",
    )
    manifest_path = args.output.with_suffix(".manifest.json")
    manifest_path.write_text(
        json.dumps(
            {
                **summary,
                "input": str(args.input.resolve()),
                "output": str(args.output.resolve()),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
