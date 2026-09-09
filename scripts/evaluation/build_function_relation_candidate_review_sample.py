from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from moongcheap_ai.demand_clustering.evaluation.function_relation_candidate_review import (
    build_candidate_relation_review_sample,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a blinded pilot from unseen retrieval candidates"
    )
    parser.add_argument(
        "--candidates",
        type=Path,
        default=Path(
            "data/reports/function_relation_candidate_set_v1/"
            "relation_candidates.csv"
        ),
    )
    parser.add_argument("--directions-per-stratum", type=int, default=8)
    parser.add_argument(
        "--seed",
        default="mfds-function-relation-candidate-pilot-v1",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise RuntimeError(f"refusing to overwrite output directory: {args.output_dir}")

    reviewer_a, reviewer_b, audit, manifest = build_candidate_relation_review_sample(
        pd.read_csv(args.candidates, dtype=str, keep_default_na=False),
        directions_per_stratum=args.directions_per_stratum,
        seed=args.seed,
    )
    args.output_dir.mkdir(parents=True)
    reviewer_a.to_csv(
        args.output_dir / "reviewer_a.csv",
        index=False,
        encoding="utf-8-sig",
    )
    reviewer_b.to_csv(
        args.output_dir / "reviewer_b.csv",
        index=False,
        encoding="utf-8-sig",
    )
    audit.to_csv(
        args.output_dir / "sampling_audit.csv",
        index=False,
        encoding="utf-8-sig",
    )
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()
