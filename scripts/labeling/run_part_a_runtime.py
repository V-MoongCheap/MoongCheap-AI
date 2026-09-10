"""Run the Part A V2.2 deterministic demand parser on CSV input."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from moongcheap_ai.data_foundation.part_a_runtime import run_part_a_batch


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Part A Consumer Demand Runtime")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--taxonomy", type=Path, default=Path("config/facet_taxonomy_v2_2.json"))
    parser.add_argument("--rules", type=Path, default=Path("config/demand_constraint_rules.json"))
    parser.add_argument("--alias-registry", type=Path, default=Path("config/model1_aliases_reviewed_v2.json"))
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--summary", type=Path)
    args = parser.parse_args()
    demands = pd.read_csv(args.input, dtype=str).fillna("")
    catalog = pd.read_csv(args.catalog, dtype=str).fillna("") if args.catalog else None
    result, summary = run_part_a_batch(
        demands,
        args.taxonomy,
        args.rules,
        args.alias_registry,
        catalog=catalog,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output, index=False, encoding="utf-8-sig")
    summary_path = args.summary or args.output.with_suffix(".summary.json")
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({**summary, "output": str(args.output), "summary": str(summary_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

