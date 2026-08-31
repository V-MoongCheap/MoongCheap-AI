from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from moongcheap_ai.erd_contract import validate_catalog_export, validate_category_seed, validate_labeled_demands


def read_table(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path) if path.suffix.lower() == ".parquet" else pd.read_csv(path, dtype=str).fillna("")


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate Backend ERD handoff files")
    parser.add_argument("--category", type=Path)
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--demand", type=Path)
    parser.add_argument("--output", type=Path, default=Path("data/reports/erd_contract_validation.json"))
    args = parser.parse_args()
    report = {}
    category_keys = None
    if args.category:
        result = validate_category_seed(read_table(args.category))
        report["category"] = result
        category_keys = set(read_table(args.category)["category_key"].astype(str)) if result["status"] != "INVALID" else None
    if args.catalog:
        report["catalog"] = validate_catalog_export(read_table(args.catalog), category_keys)
    if args.demand:
        report["demand"] = validate_labeled_demands(read_table(args.demand))
    report["status"] = "INVALID" if any(value["status"] == "INVALID" for value in report.values() if isinstance(value, dict)) else "VALID"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(report)
    if report["status"] == "INVALID":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
