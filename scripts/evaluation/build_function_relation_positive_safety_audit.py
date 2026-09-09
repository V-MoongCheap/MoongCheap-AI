from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from moongcheap_ai.demand_clustering.evaluation.function_relation_pilot import (
    build_positive_relation_reaudit,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a conservative re-audit of positive function relations"
    )
    parser.add_argument("--input", action="append", type=Path, default=[])
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--seed",
        default="mfds-function-positive-safety-audit-v1",
    )
    args = parser.parse_args()
    if not args.input:
        raise ValueError("at least one --input is required")
    if args.output_dir.exists():
        raise RuntimeError(f"refusing to overwrite output directory: {args.output_dir}")
    source = pd.concat([
        pd.read_csv(path, dtype=str, keep_default_na=False)
        for path in args.input
    ], ignore_index=True)
    reviewer_a, reviewer_b, adjudication, manifest = (
        build_positive_relation_reaudit(source, seed=args.seed)
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
    adjudication.to_csv(
        args.output_dir / "adjudication.csv",
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
