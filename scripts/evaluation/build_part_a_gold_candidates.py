"""Build a human-reviewable Part A V2.2 evaluation candidate set.

This produces proposed cases, not a fixed Gold Set. No row is considered
approved until a reviewer fills the review columns.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TAXONOMY = ROOT / "config/facet_taxonomy_v2_2.json"
DEFAULT_REFERENCE = ROOT / "tests/demand_constraints/fixtures/v042_approved_eval.csv"
DEFAULT_OUTPUT = ROOT / "data/review/part_a_v2_2_gold_human_review.csv"
DEFAULT_REPORT = ROOT / "reports/part_a_v2_2_gold_candidate_report.md"

REVIEW_COLUMNS = [
    "case_id", "split_candidate", "category_id", "category_name", "extra_requirement",
    "is_substitutable", "proposed_expected_status", "proposed_expected_mode",
    "proposed_expected_constraints", "proposed_expected_preference_groups",
    "scenario_type", "grounding_source", "generation_reason", "reviewer_status",
    "corrected_expected_status", "corrected_expected_mode", "corrected_expected_constraints",
    "reviewer_note",
]


def _mode(constraints: list[dict[str, Any]]) -> str:
    types = {str(item.get("constraint_type", "")).upper() for item in constraints}
    if "MUST" in types and "EXCLUDE" in types:
        return "MIXED"
    if "MUST" in types:
        return "MUST"
    if "EXCLUDE" in types:
        return "EXCLUDE"
    if "PREFER" in types:
        return "PREFER"
    return "NONE"


def _load_taxonomy(path: Path) -> tuple[dict[str, str], dict[str, list[dict[str, Any]]]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    names = {item["category_id"]: item.get("category_name", "") for item in data["categories"]}
    values: dict[str, list[dict[str, Any]]] = {}
    for category in data["categories"]:
        category_values: list[dict[str, Any]] = []
        for facet in category["facets"]:
            for value in facet["values"]:
                if int(value["code"]) == 0 or not str(value.get("value", "")).strip():
                    continue
                category_values.append({"facet_name": facet["name"], "value_code": int(value["code"]), "value": value["value"]})
        values[category["category_id"]] = category_values
    return names, values


def _reference_rows(path: Path) -> list[dict[str, Any]]:
    frame = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8")
    rows: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        constraints = json.loads(row["expected_constraints_json"])
        rows.append({
            "category_id": row["category_id"],
            "extra_requirement": row["extra_requirement"],
            "status": row["expected_status"],
            "constraints": constraints,
            "scenario_type": row["scenario"],
            "grounding_source": "human-reviewed v042 evaluation fixture",
            "generation_reason": "Existing reviewed expression pattern reused as a candidate; approval is pending.",
        })
    return rows


def _new_rows(values: dict[str, list[dict[str, Any]]], count: int, seed: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    categories = sorted(values)
    rows: list[dict[str, Any]] = []
    templates = [
        ("PREFER", "{value} 조건을 선호합니다.", "PREFER"),
        ("MUST", "{value}인 제품으로 찾아주세요.", "MUST"),
        ("EXCLUDE", "{value}는 제외해주세요.", "EXCLUDE"),
    ]
    for index in range(count):
        category = categories[index % len(categories)]
        choices = values[category]
        first = choices[index % len(choices)]
        kind, text, constraint_type = templates[index % len(templates)]
        constraint = {**first, "constraint_type": constraint_type}
        rows.append({
            "category_id": category,
            "extra_requirement": text.format(value=first["value"]),
            "status": "PARSED",
            "constraints": [constraint],
            "scenario_type": f"GROUNDED_{kind}_CANDIDATE",
            "grounding_source": "Facet Taxonomy V2.2 canonical value",
            "generation_reason": "Deterministic candidate from an existing category-local canonical value; human review required.",
        })
    rng.shuffle(rows)
    return rows


def _challenge_rows(values: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Compose policy-edge candidates from real category-local values."""
    categories = sorted(values)
    rows: list[dict[str, Any]] = []
    for index in range(50):
        category = categories[index % len(categories)]
        choices = values[category]
        first = choices[index % len(choices)]
        second = choices[(index + 1) % len(choices)]
        if index < 15:
            constraints = [
                {**first, "constraint_type": "MUST"},
                {**second, "constraint_type": "PREFER"},
            ]
            text = f"{first['value']}는 꼭 포함하고, {second['value']}도 가능하면 선호해요."
            status = "PARSED"
            scenario = "MULTI_CONSTRAINT_CANDIDATE"
        elif index < 23:
            members = [{**first, "constraint_type": "PREFER"}, {**second, "constraint_type": "PREFER"}]
            constraints = []
            text = f"{first['value']} 또는 {second['value']}면 괜찮아요."
            status = "PARSED"
            scenario = "ANY_OF_CANDIDATE"
            rows.append({
                "category_id": category, "extra_requirement": text, "status": status,
                "constraints": constraints, "preference_groups": [{"operator": "ANY_OF", "aggregation": "MAX", "members": members}],
                "scenario_type": scenario, "grounding_source": "V2.2 canonical values + runtime policy fixture",
                "generation_reason": "Alternative-value policy candidate; parser output must be verified by a reviewer.",
            })
            continue
        elif index < 29:
            constraints = []
            text = "먹기 편하고 부담 없는 제품이면 좋겠어요."
            status = "PASSTHROUGH"
            scenario = "PASSTHROUGH_CANDIDATE"
        elif index < 35:
            constraints = []
            text = f"{first['value']} 아니면 {second['value']}로 정확히 골라주세요."
            status = "CONFLICT"
            scenario = "CONFLICT_CANDIDATE"
        elif index < 40:
            constraints = []
            text = "조건을 여러 가지로 생각 중인데 어떤 기준이 맞을지 잘 모르겠어요."
            status = "REVIEW"
            scenario = "REVIEW_CANDIDATE"
        elif index < 45:
            constraints = []
            text = ""
            status = "NOT_APPLICABLE"
            scenario = "NOT_APPLICABLE_CANDIDATE"
        else:
            constraints = []
            text = ""
            status = "NONE"
            scenario = "NONE_CANDIDATE"
        rows.append({
            "category_id": category, "extra_requirement": text, "status": status,
            "constraints": constraints, "preference_groups": [], "is_substitutable": status != "NOT_APPLICABLE",
            "scenario_type": scenario, "grounding_source": "V2.2 canonical values + runtime policy fixture",
            "generation_reason": "Runtime edge-case candidate; proposed status is not an automatic Gold label.",
        })
    return rows


def _record(row: dict[str, Any], case_id: str, split: str, category_name: str) -> dict[str, Any]:
    constraints = row["constraints"]
    preference_groups = row.get("preference_groups", [])
    return {
        "case_id": case_id,
        "split_candidate": split,
        "category_id": row["category_id"],
        "category_name": category_name,
        "extra_requirement": row["extra_requirement"],
        "is_substitutable": str(row.get("is_substitutable", True)).lower(),
        "proposed_expected_status": row["status"],
        "proposed_expected_mode": "ANY_OF" if preference_groups else _mode(constraints),
        "proposed_expected_constraints": json.dumps(constraints, ensure_ascii=False, separators=(",", ":")),
        "proposed_expected_preference_groups": json.dumps(preference_groups, ensure_ascii=False, separators=(",", ":")),
        "scenario_type": row["scenario_type"],
        "grounding_source": row["grounding_source"],
        "generation_reason": row["generation_reason"],
        "reviewer_status": "PENDING_REVIEW",
        "corrected_expected_status": "",
        "corrected_expected_mode": "",
        "corrected_expected_constraints": "",
        "reviewer_note": "",
    }


def build_candidate_set(taxonomy_path: Path = DEFAULT_TAXONOMY, reference_path: Path = DEFAULT_REFERENCE, seed: int = 42) -> pd.DataFrame:
    names, values = _load_taxonomy(taxonomy_path)
    reference = _reference_rows(reference_path)
    generated = _new_rows(values, 21, seed) + _challenge_rows(values)
    rows = reference + generated
    # Preserve a fixed review split, independent of generation order.
    records = []
    for index, row in enumerate(rows):
        split = "STANDARD" if index < 150 else "CHALLENGE"
        records.append(_record(row, f"part-a-v2-2-{index + 1:03d}", split, names.get(row["category_id"], "")))
    return pd.DataFrame(records, columns=REVIEW_COLUMNS)


def write_report(frame: pd.DataFrame, path: Path, reference_count: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Part A V2.2 Gold Candidate Report", "",
        "이 산출물은 고정 Gold Set이 아니라 Human Review 전 후보 세트다.",
        "모든 행은 `PENDING_REVIEW`이며, proposed 값은 정답으로 확정되지 않았다.", "",
        "## Summary", "",
        f"- Candidate rows: {len(frame)}", "- Standard candidates: 150", "- Challenge candidates: 50",
        f"- Reused human-reviewed reference rows: {reference_count}",
        f"- Newly composed candidates: {len(frame) - reference_count}",
        f"- Category count: {frame['category_id'].nunique()}",
        f"- Pending review rows: {int(frame['reviewer_status'].eq('PENDING_REVIEW').sum())}", "",
        "## Provenance", "",
        "- Existing 200-row Legacy Gold: `NOT_FOUND`.",
        "- Existing 72.50% metric remains `LEGACY_EXPERIMENT_REFERENCE` and is not used as a baseline here.",
        "- 129 rows come from the tracked human-reviewed v042 evaluation fixture.",
        "- Remaining rows are deterministic candidate compositions from V2.2 category-local canonical values.",
        "- MFDS raw product facts were not available in the tracked workspace, so they are not claimed as grounding for these rows.",
        "- No row is automatically finalized as Gold.", "",
        "## Review Policy", "",
        "Reviewer must verify category, status, mode, constraints, and whether the expression is supported by the selected grounding source.",
        "After review, only an explicit finalization script may export STANDARD 150 and CHALLENGE 50 as fixed evaluation sets.", "",
        "## Scenario / Category Distribution", "",
        frame.groupby(["split_candidate", "scenario_type"], dropna=False).size().to_string().rstrip(), "",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--taxonomy", type=Path, default=DEFAULT_TAXONOMY)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    frame = build_candidate_set(args.taxonomy, args.reference, args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(args.output, index=False, encoding="utf-8-sig")
    write_report(frame, args.report, min(len(pd.read_csv(args.reference, dtype=str)), len(frame)))
    print({"status": "CANDIDATES_CREATED", "rows": len(frame), "standard": 150, "challenge": 50, "review_status": "PENDING_REVIEW"})


if __name__ == "__main__":
    main()
