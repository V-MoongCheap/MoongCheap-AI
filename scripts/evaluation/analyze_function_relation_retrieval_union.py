from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from moongcheap_ai.demand_clustering.evaluation.function_relation_retrieval_evaluation import (
    evaluate_known_positive_rank_union,
)


def _named_path(value: str) -> tuple[str, Path]:
    name, separator, raw_path = value.partition("=")
    if not separator or not name.strip() or not raw_path.strip():
        raise argparse.ArgumentTypeError("rank input must use NAME=PATH")
    return name.strip(), Path(raw_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze the union of known-positive retrieval ranks"
    )
    parser.add_argument(
        "--ranks",
        action="append",
        type=_named_path,
        default=[],
        help="Repeatable NAME=known_positive_ranks.csv",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if len({name for name, _ in args.ranks}) != len(args.ranks):
        raise ValueError("rank input names must be unique")
    result = evaluate_known_positive_rank_union({
        name: pd.read_csv(path, dtype=str, keep_default_na=False)
        for name, path in args.ranks
    })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
