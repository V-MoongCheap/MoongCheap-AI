from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from moongcheap_ai.demand_clustering.evaluation.function_relation_pilot import (
    build_function_relation_pilot,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a blinded two-reviewer MFDS function pilot"
    )
    parser.add_argument(
        "--review",
        type=Path,
        default=Path("data/reports/mfds_function_relation_review_v1.csv"),
    )
    parser.add_argument(
        "--audit",
        type=Path,
        default=Path(
            "data/reports/mfds_function_relation_sampling_audit_v1.csv"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/reports/function_relation_pilot_v1"),
    )
    parser.add_argument("--pairs-per-stratum", type=int, default=3)
    parser.add_argument("--seed", default="mfds-function-relation-pilot-v1")
    parser.add_argument(
        "--exclude-review",
        action="append",
        type=Path,
        default=[],
        help="Optional prior reviewer CSV whose undirected pairs must be excluded",
    )
    parser.add_argument(
        "--exclude-claims-from-review",
        action="append",
        type=Path,
        default=[],
        help="Optional prior reviewer CSV whose claim IDs must all be excluded",
    )
    parser.add_argument(
        "--exclude-pair-texts-from-review",
        action="append",
        type=Path,
        default=[],
        help="Optional prior reviewer CSV whose undirected text pairs are excluded",
    )
    args = parser.parse_args()

    review = pd.read_csv(args.review, dtype=str, keep_default_na=False)
    audit = pd.read_csv(args.audit, dtype=str, keep_default_na=False)
    excluded_direction_ids: list[str] = []
    for exclude_review in args.exclude_review:
        excluded = pd.read_csv(
            exclude_review,
            dtype=str,
            keep_default_na=False,
        )
        if "direction_id" not in excluded.columns:
            raise ValueError("exclude-review must contain direction_id")
        excluded_direction_ids.extend(excluded["direction_id"].tolist())
    excluded_claim_ids: list[str] = []
    for exclude_review in args.exclude_claims_from_review:
        excluded = pd.read_csv(
            exclude_review,
            dtype=str,
            keep_default_na=False,
        )
        required_claim_columns = {"source_claim_id", "candidate_claim_id"}
        if missing := sorted(required_claim_columns - set(excluded.columns)):
            raise ValueError(
                "exclude-claims-from-review missing columns: "
                + ", ".join(missing)
            )
        excluded_claim_ids.extend(excluded["source_claim_id"].tolist())
        excluded_claim_ids.extend(excluded["candidate_claim_id"].tolist())
    excluded_text_pairs: list[tuple[str, str]] = []
    for exclude_review in args.exclude_pair_texts_from_review:
        excluded = pd.read_csv(
            exclude_review,
            dtype=str,
            keep_default_na=False,
        )
        required_text_columns = {"source_claim_text", "candidate_claim_text"}
        if missing := sorted(required_text_columns - set(excluded.columns)):
            raise ValueError(
                "exclude-pair-texts-from-review missing columns: "
                + ", ".join(missing)
            )
        excluded_text_pairs.extend(zip(
            excluded["source_claim_text"],
            excluded["candidate_claim_text"],
        ))
    reviewer_a, reviewer_b, adjudication, manifest = (
        build_function_relation_pilot(
            review,
            audit,
            pairs_per_stratum=args.pairs_per_stratum,
            seed=args.seed,
            excluded_direction_ids=excluded_direction_ids,
            excluded_claim_ids=excluded_claim_ids,
            excluded_text_pairs=excluded_text_pairs,
        )
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_paths = {
        "reviewerA": args.output_dir / "reviewer_a.csv",
        "reviewerB": args.output_dir / "reviewer_b.csv",
        "adjudication": args.output_dir / "adjudication.csv",
        "manifest": args.output_dir / "manifest.json",
    }
    reviewer_a.to_csv(output_paths["reviewerA"], index=False, encoding="utf-8-sig")
    reviewer_b.to_csv(output_paths["reviewerB"], index=False, encoding="utf-8-sig")
    adjudication.to_csv(
        output_paths["adjudication"],
        index=False,
        encoding="utf-8-sig",
    )
    output_paths["manifest"].write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()
