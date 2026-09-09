from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from moongcheap_ai.demand_clustering.evaluation.function_relation_review import (
    build_function_relation_review_set,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a blinded directional MFDS function review set"
    )
    parser.add_argument(
        "--claims",
        type=Path,
        default=Path("data/reports/mfds_function_claim_candidates_v1.csv"),
    )
    parser.add_argument(
        "--review",
        type=Path,
        default=Path("data/reports/mfds_function_relation_review_v1.csv"),
    )
    parser.add_argument(
        "--audit",
        type=Path,
        default=Path("data/reports/mfds_function_relation_sampling_audit_v1.csv"),
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("data/reports/mfds_function_relation_manifest_v1.json"),
    )
    parser.add_argument("--pairs-per-stratum", type=int, default=30)
    parser.add_argument("--seed", default="mfds-function-relation-v1")
    args = parser.parse_args()

    claims = pd.read_csv(args.claims, dtype=str, keep_default_na=False)
    review, audit, manifest = build_function_relation_review_set(
        claims,
        pairs_per_stratum=args.pairs_per_stratum,
        seed=args.seed,
    )
    for path in (args.review, args.audit, args.manifest):
        path.parent.mkdir(parents=True, exist_ok=True)
    review.to_csv(args.review, index=False, encoding="utf-8-sig")
    audit.to_csv(args.audit, index=False, encoding="utf-8-sig")
    args.manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()
