from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from moongcheap_ai.demand_clustering.evaluation.function_relation_pilot_analysis import (
    analyze_function_relation_pilot,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze the adjudicated external-LLM function pilot"
    )
    base = Path("data/reports/function_relation_pilot_v1/llm_consensus_v1")
    parser.add_argument(
        "--independent-status",
        type=Path,
        default=base / "review_status.csv",
    )
    parser.add_argument(
        "--adjudicated-status",
        type=Path,
        default=base / "adjudicated_review_status.csv",
    )
    parser.add_argument(
        "--audit",
        type=Path,
        default=Path(
            "data/reports/mfds_function_relation_sampling_audit_v1.csv"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=base / "analysis.json",
    )
    args = parser.parse_args()

    analysis = analyze_function_relation_pilot(
        pd.read_csv(args.independent_status, dtype=str, keep_default_na=False),
        pd.read_csv(args.adjudicated_status, dtype=str, keep_default_na=False),
        pd.read_csv(args.audit, dtype=str, keep_default_na=False),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(analysis, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(analysis, ensure_ascii=False))


if __name__ == "__main__":
    main()
