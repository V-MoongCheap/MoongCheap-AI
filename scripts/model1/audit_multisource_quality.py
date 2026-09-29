"""Audit Model 1 candidates before they enter the human-review queue.

This is an evidence gate, not a taxonomy approver.  It checks that every
candidate can be traced to the exact Model 1 input and reports model-only,
duplicate, missing-reason, and unobserved-value cases separately.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd


REQUIRED_INPUT_COLUMNS = {"category_key", "source_product_id"}
REQUIRED_CANDIDATE_COLUMNS = {
    "model",
    "category_key",
    "name",
    "value",
    "source_product_id",
    "selection_reason",
    "value_reason",
    "observed_row_count",
}


def _read(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    if path.suffix.lower() in {".jsonl", ".ndjson"}:
        return pd.read_json(path, lines=True).fillna("")
    return pd.read_csv(path, dtype=str).fillna("")


def audit(input_frame: pd.DataFrame, candidate_frame: pd.DataFrame) -> dict[str, Any]:
    missing_input = sorted(REQUIRED_INPUT_COLUMNS - set(input_frame.columns))
    missing_candidates = sorted(REQUIRED_CANDIDATE_COLUMNS - set(candidate_frame.columns))
    if missing_input or missing_candidates:
        raise ValueError(
            f"missing columns: input={missing_input}, candidates={missing_candidates}"
        )

    input_ids = set(input_frame["source_product_id"].astype(str))
    input_pairs = set(
        zip(input_frame["category_key"].astype(str), input_frame["source_product_id"].astype(str))
    )
    candidates = candidate_frame.copy()
    candidate_keys = list(
        zip(candidates["category_key"].astype(str), candidates["name"].astype(str), candidates["value"].astype(str))
    )
    duplicate_count = len(candidate_keys) - len(set(candidate_keys))
    missing_evidence = ~candidates["source_product_id"].astype(str).isin(input_ids)
    category_mismatch = ~candidates.apply(
        lambda row: (str(row["category_key"]), str(row["source_product_id"])) in input_pairs,
        axis=1,
    )
    unobserved = pd.to_numeric(candidates["observed_row_count"], errors="coerce").fillna(0).le(0)
    missing_reason = candidates["selection_reason"].astype(str).str.strip().eq("") | candidates[
        "value_reason"
    ].astype(str).str.strip().eq("")
    model_only = candidates.groupby(
        ["category_key", "name", "value"], dropna=False
    )["model"].nunique().le(1)

    issues = {
        "missing_source_product": int(missing_evidence.sum()),
        "source_category_mismatch": int(category_mismatch.sum()),
        "unobserved_value": int(unobserved.sum()),
        "missing_model_reason": int(missing_reason.sum()),
        "duplicate_candidate_keys": int(duplicate_count),
        "model_singleton_groups": int(model_only.sum()),
    }
    blocking = {
        key: value
        for key, value in issues.items()
        if key not in {"model_singleton_groups", "missing_model_reason"} and value
    }
    status = "PASS" if not blocking else "REVIEW_REQUIRED"
    return {
        "status": status,
        "input_rows": len(input_frame),
        "candidate_rows": len(candidates),
        "category_count": int(candidates["category_key"].nunique()),
        "model_counts": dict(Counter(candidates["model"])),
        "issues": issues,
        "blocking_issues": blocking,
        "promotion_policy": "Only evidence-backed candidates may proceed; model-only candidates remain review-only.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit(_read(args.input), _read(args.candidates))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
