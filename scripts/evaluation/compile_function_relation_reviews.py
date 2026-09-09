from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from moongcheap_ai.demand_clustering.evaluation.function_relation_annotation import (
    compile_function_relation_reviews,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate and combine two independent MFDS function reviews"
    )
    parser.add_argument(
        "--reviewer-a",
        type=Path,
        default=Path("data/reports/function_relation_pilot_v1/reviewer_a.csv"),
    )
    parser.add_argument(
        "--rubric-version",
        choices=("v1", "v2", "v2.1", "v2.2", "v3"),
        default="v1",
    )
    parser.add_argument(
        "--reviewer-b",
        type=Path,
        default=Path("data/reports/function_relation_pilot_v1/reviewer_b.csv"),
    )
    parser.add_argument(
        "--adjudication-scope",
        choices=("label-and-reason", "label-only"),
        default="label-and-reason",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/reports/function_relation_pilot_v1/review_status.csv"),
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=Path(
            "data/reports/function_relation_pilot_v1/review_status_summary.json"
        ),
    )
    args = parser.parse_args()

    reviewer_a = pd.read_csv(args.reviewer_a, dtype=str, keep_default_na=False)
    reviewer_b = pd.read_csv(args.reviewer_b, dtype=str, keep_default_na=False)
    combined, summary = compile_function_relation_reviews(
        reviewer_a,
        reviewer_b,
        rubric_version=args.rubric_version,
        adjudication_scope=args.adjudication_scope,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(args.output, index=False, encoding="utf-8-sig")
    args.summary.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
