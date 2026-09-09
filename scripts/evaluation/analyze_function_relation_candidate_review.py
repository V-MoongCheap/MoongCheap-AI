from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from moongcheap_ai.demand_clustering.evaluation.function_relation_candidate_review import (
    analyze_candidate_relation_review,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze a retrieval-stratified function candidate review"
    )
    base = Path("data/reports/function_relation_candidate_review_pilot_v1")
    parser.add_argument(
        "--independent-status",
        type=Path,
        default=base / "llm_consensus_v3/review_status.csv",
    )
    parser.add_argument(
        "--adjudicated-status",
        type=Path,
        default=base / "llm_consensus_v3/adjudicated_review_status.csv",
    )
    parser.add_argument(
        "--audit",
        type=Path,
        default=base / "sampling_audit.csv",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=base / "llm_consensus_v3/analysis.json",
    )
    args = parser.parse_args()
    if args.output.exists():
        raise RuntimeError(f"refusing to overwrite output: {args.output}")

    result = analyze_candidate_relation_review(
        pd.read_csv(args.independent_status, dtype=str, keep_default_na=False),
        pd.read_csv(args.adjudicated_status, dtype=str, keep_default_na=False),
        pd.read_csv(args.audit, dtype=str, keep_default_na=False),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
