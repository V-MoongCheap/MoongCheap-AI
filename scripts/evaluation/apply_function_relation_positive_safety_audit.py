from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from moongcheap_ai.demand_clustering.evaluation.function_relation_annotation import (
    apply_positive_relation_safety_audit,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Apply positive relation safety audit to adjudicated labels"
    )
    parser.add_argument("--base", action="append", type=Path, default=[])
    parser.add_argument("--safety-status", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()
    if not args.base:
        raise ValueError("at least one --base is required")
    for path in (args.output, args.summary):
        if path.exists():
            raise RuntimeError(f"refusing to overwrite output: {path}")
    base = pd.concat([
        pd.read_csv(path, dtype=str, keep_default_na=False)
        for path in args.base
    ], ignore_index=True)
    output, summary = apply_positive_relation_safety_audit(
        base,
        pd.read_csv(args.safety_status, dtype=str, keep_default_na=False),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(args.output, index=False, encoding="utf-8-sig")
    args.summary.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
