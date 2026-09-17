"""Combine Model 2 review decisions with B parser output without auto-approving Gold."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def build(review_path: Path, runtime_path: Path, output_path: Path, gold_path: Path) -> dict[str, int]:
    review = pd.read_csv(review_path, dtype=str, encoding="utf-8-sig").fillna("")
    runtime = pd.read_csv(runtime_path, dtype=str, encoding="utf-8-sig").fillna("")
    required = {"demand_id", "review_decision", "review_note"}
    if missing := sorted(required - set(review.columns)):
        raise ValueError("review file missing columns: " + ", ".join(missing))
    runtime_columns = [
        column for column in ("demand_id", "status", "effectiveRequirementMode", "constraints", "label", "facet_values")
        if column in runtime.columns
    ]
    result = review.merge(runtime[runtime_columns], on="demand_id", how="left", validate="one_to_one")
    result["corrected_extra_requirement"] = ""
    result["corrected_expected_constraints"] = result.get("constraints", "[]")
    result["correction_source"] = "B_PARSER_CANDIDATE_NOT_HUMAN_APPROVED"
    result["gold_eligibility"] = result["review_decision"].map({
        "APPROVE": "GOLD_CANDIDATE_PENDING_FINAL_CHECK",
        "EDIT": "PENDING_EDIT_AND_REVIEW",
        "REJECT": "EXCLUDED",
        "UNCERTAIN": "PENDING_POLICY",
    }).fillna("INVALID_REVIEW_DECISION")
    result["resolution_note"] = result.apply(
        lambda row: "No structured correction supplied; preserve original text and review note." if row["review_decision"] == "EDIT" else "",
        axis=1,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    gold_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output_path, index=False, encoding="utf-8-sig")
    gold = result[result["gold_eligibility"] == "GOLD_CANDIDATE_PENDING_FINAL_CHECK"].copy()
    gold.to_csv(gold_path, index=False, encoding="utf-8-sig")
    return {
        "review_rows": len(result),
        "gold_candidate_rows": len(gold),
        "edit_rows": int((result["review_decision"] == "EDIT").sum()),
        "rejected_rows": int((result["review_decision"] == "REJECT").sum()),
        "uncertain_rows": int((result["review_decision"] == "UNCERTAIN").sum()),
        "parser_status_missing_rows": int(result["status"].eq("").sum()),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--gold-output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.review, args.runtime, args.output, args.gold_output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
