"""Build a human-reviewable Part A V2.2 evaluation candidate set.

This produces proposed cases, not a fixed Gold Set. No row is considered
approved until a reviewer fills the review columns.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import unicodedata
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
    "scenario_type", "grounding_source", "generation_reason", "candidate_origin",
    "source_reference", "existing_test_case_id", "parser_exposure", "evaluation_partition_candidate",
    "reviewer_status",
    "corrected_expected_status", "corrected_expected_mode", "corrected_expected_constraints",
    "corrected_expected_preference_groups",
    "proposed_expected_effective_requirement_mode", "corrected_expected_effective_requirement_mode",
    "proposed_expected_passthrough_text", "corrected_expected_passthrough_text",
    "reviewer_note",
]


def _mode(constraints: list[dict[str, Any]]) -> str:
    types = {str(item.get("constraint_type", "")).upper() for item in constraints}
    if "MUST" in types and ("EXCLUDE" in types or "PREFER" in types):
        return "MIXED"
    if "EXCLUDE" in types and "PREFER" in types:
        return "MIXED"
    if "MUST" in types:
        return "MUST"
    if "EXCLUDE" in types:
        return "EXCLUDE"
    if "PREFER" in types:
        return "PREFER"
    return "NONE"


def _effective_mode(status: str) -> str:
    if status == "PARSED":
        return "STRUCTURED"
    if status == "PASSTHROUGH":
        return "SEMANTIC_TEXT"
    return "NONE"


def _dedup_key(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(text)).strip()
    return re.sub(r"[^0-9A-Za-z가-힣]+", "", normalized)


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
            "candidate_origin": "EXISTING_REVIEWED_FIXTURE",
            "source_reference": "tests/demand_constraints/fixtures/v042_approved_eval.csv",
            "existing_test_case_id": row["sample_id"],
            "parser_exposure": "KNOWN_TO_EXISTING_TESTS",
        })
    return rows


def _new_rows(values: dict[str, list[dict[str, Any]]], count: int, seed: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    categories = sorted(values)
    rows: list[dict[str, Any]] = []
    used_texts: set[str] = set()
    templates = [
        ("PREFER", "{value} 포함 여부를 중요하게 봐요.", "PREFER"),
        ("MUST", "{value} 포함 제품을 찾습니다.", "MUST"),
        ("EXCLUDE", "{value} 제외 제품을 찾습니다.", "EXCLUDE"),
    ]
    for index in range(count):
        category = categories[index % len(categories)]
        choices = values[category]
        first = choices[index % len(choices)]
        kind, text, constraint_type = templates[index % len(templates)]
        rendered = text.format(value=first["value"])
        if rendered in used_texts:
            rendered = {
                "PREFER": f"제품을 고를 때 {first['value']} 포함 여부를 먼저 봐요.",
                "MUST": f"이번 요청은 {first['value']} 포함 제품으로 찾아주세요.",
                "EXCLUDE": f"이번 요청에서는 {first['value']} 없는 제품을 찾아주세요.",
            }[kind]
        if rendered in used_texts:
            rendered = f"{first['value']} 포함 여부를 이번에는 먼저 확인해 주세요."
        used_texts.add(rendered)
        constraint = {**first, "constraint_type": constraint_type}
        rows.append({
            "category_id": category,
            "extra_requirement": rendered,
            "status": "PARSED",
            "constraints": [constraint],
            "scenario_type": f"GROUNDED_{kind}_CANDIDATE",
            "grounding_source": "Facet Taxonomy V2.2 canonical value",
            "generation_reason": "Deterministic candidate from an existing category-local canonical value; human review required.",
            "candidate_origin": "NEW_STANDARD_CANDIDATE",
            "source_reference": "config/facet_taxonomy_v2_2.json",
            "existing_test_case_id": "",
            "parser_exposure": "NEW_UNSEEN_CANDIDATE",
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
            text = f"{first['value']} 포함은 필수이고, {second['value']} 포함은 선호합니다."
            status = "PARSED"
            scenario = "MULTI_CONSTRAINT_CANDIDATE"
        elif index < 23:
            members = [{**first, "constraint_type": "PREFER"}, {**second, "constraint_type": "PREFER"}]
            constraints = []
            same_facet = [item for item in choices if item["facet_name"] == first["facet_name"]]
            if len(same_facet) >= 2:
                first, second = same_facet[0], same_facet[1]
                members = [{**first, "constraint_type": "PREFER"}, {**second, "constraint_type": "PREFER"}]
            text = (
                f"{first['value']} 또는 {second['value']}면 괜찮아요."
                if index % 2 == 0
                else f"{first['value']} 또는 {second['value']} 중 하나면 괜찮아요."
            )
            status = "PARSED"
            scenario = "ANY_OF_CANDIDATE"
            rows.append({
                "category_id": category, "extra_requirement": text, "status": status,
                "constraints": constraints, "preference_groups": [{"operator": "ANY_OF", "aggregation": "MAX", "members": members}],
                "scenario_type": scenario, "grounding_source": "V2.2 canonical values + runtime policy fixture",
                "generation_reason": "Alternative-value policy candidate; parser output must be verified by a reviewer.",
                "candidate_origin": "NEW_CHALLENGE_CANDIDATE",
                "source_reference": "config/facet_taxonomy_v2_2.json; runtime policy fixture",
                "existing_test_case_id": "",
                "parser_exposure": "NEW_UNSEEN_CANDIDATE",
            })
            continue
        elif index < 29:
            constraints = []
            text = [
                "개별 포장이라 휴대하기 편하면 좋겠어요.",
                "섭취 후 속이 편안하면 좋겠어요.",
                "맛이 강하지 않고 부담 없으면 좋겠어요.",
                "보관하기 쉬운 포장이면 좋겠어요.",
                "물에 잘 섞이면 좋겠어요.",
                "알약이 작아 삼키기 편하면 좋겠어요.",
            ][index - 29]
            status = "PASSTHROUGH"
            scenario = "PASSTHROUGH_CANDIDATE"
        elif index < 35:
            constraints = []
            text = f"{first['value']} 포함과 제외를 동시에 요구합니다."
            status = "CONFLICT"
            scenario = "CONFLICT_CANDIDATE"
        elif index < 40:
            constraints = []
            text = [
                "조건을 여러 가지로 생각 중인데 어떤 기준이 맞을지 아직 모르겠어요.",
                "아직 원하는 조건을 정하지 못해서 비교 기준을 고민하고 있어요.",
                "여러 조건 중 무엇을 우선할지 결정하지 못했어요.",
                "구매 조건을 더 생각해 본 뒤에 정하고 싶어요.",
                "지금은 특정 조건을 하나로 정하기 어려워요.",
            ][index - 35]
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
            "candidate_origin": "NEW_CHALLENGE_CANDIDATE",
            "source_reference": "config/facet_taxonomy_v2_2.json; runtime policy fixture",
            "existing_test_case_id": "",
            "parser_exposure": "NEW_UNSEEN_CANDIDATE",
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
        "candidate_origin": row["candidate_origin"],
        "source_reference": row["source_reference"],
        "existing_test_case_id": row["existing_test_case_id"],
        "parser_exposure": row["parser_exposure"],
        "evaluation_partition_candidate": (
            "CHALLENGE" if split == "CHALLENGE" else ("DEV" if int(case_id.rsplit("-", 1)[-1]) <= 100 else "HOLDOUT")
        ),
        "reviewer_status": "PENDING_REVIEW",
        "corrected_expected_status": "",
        "corrected_expected_mode": "",
        "corrected_expected_constraints": "",
        "corrected_expected_preference_groups": "",
        "proposed_expected_effective_requirement_mode": _effective_mode(row["status"]),
        "corrected_expected_effective_requirement_mode": "",
        "proposed_expected_passthrough_text": row["extra_requirement"] if row["status"] == "PASSTHROUGH" else "",
        "corrected_expected_passthrough_text": "",
        "reviewer_note": "",
    }


def _apply_quality_patches(frame: pd.DataFrame) -> pd.DataFrame:
    """Apply deterministic corrections found during candidate QA.

    These are candidate improvements only. Reviewer status remains pending and
    taxonomy changes are deliberately excluded from this step.
    """
    by_id = frame.set_index("case_id")

    # The phrase explicitly asks to find products containing this value.
    row = "part-a-v2-2-121"
    constraints = json.loads(by_id.at[row, "proposed_expected_constraints"])
    for item in constraints:
        item["constraint_type"] = "MUST"
    by_id.at[row, "proposed_expected_constraints"] = json.dumps(
        constraints, ensure_ascii=False, separators=(",", ":")
    )
    by_id.at[row, "proposed_expected_mode"] = "MUST"

    # The taxonomy uses the same daily-frequency value in this sentence, but
    # the wording expresses a preference rather than a hard requirement.
    row = "part-a-v2-2-121"
    by_id.at[row, "proposed_expected_effective_requirement_mode"] = "STRUCTURED"

    # Avoid using a catch-all product-form value in a holdout example.
    row = "part-a-v2-2-129"
    constraints = json.loads(by_id.at[row, "proposed_expected_constraints"])
    constraints[0].update({"value_code": 1, "value": "캡슐"})
    by_id.at[row, "proposed_expected_constraints"] = json.dumps(
        constraints, ensure_ascii=False, separators=(",", ":")
    )
    by_id.at[row, "extra_requirement"] = "캡슐 제형이 포함된 제품을 찾아주세요."

    text_replacements = {
        "part-a-v2-2-149": "오메가-3지방산함유유지가 포함된 제품을 찾습니다.",
        "part-a-v2-2-167": "바나바잎 추출물 또는 녹차추출물, 바나바잎 추출물 중 하나면 괜찮아요.",
        "part-a-v2-2-173": "캡슐 또는 분말이면 괜찮아요.",
        "part-a-v2-2-180": "겔은 반드시 포함하고, 겔은 제외해주세요.",
        "part-a-v2-2-181": "감태추출물은 반드시 포함하고, 감태추출물은 제외해주세요.",
        "part-a-v2-2-182": "액상은 반드시 포함하고, 액상은 제외해주세요.",
        "part-a-v2-2-183": "녹차추출물, 바나바잎 추출물 조합은 반드시 포함하고, 같은 조합은 제외해주세요.",
        "part-a-v2-2-184": "과립은 반드시 포함하고, 과립은 제외해주세요.",
        "part-a-v2-2-185": "마리골드꽃추출물, 베타카로틴 조합은 반드시 포함하고, 같은 조합은 제외해주세요.",
        "part-a-v2-2-191": "반드시 캡슐 제품이면 좋겠어요.",
        "part-a-v2-2-192": "분말은 제외해주세요.",
        "part-a-v2-2-193": "가능하면 정 형태가 좋겠어요.",
        "part-a-v2-2-194": "하루 한 번 먹는 제품이면 좋겠어요.",
        "part-a-v2-2-195": "캡슐 또는 분말 조건을 참고해 주세요.",
    }
    for case_id, text in text_replacements.items():
        by_id.at[case_id, "extra_requirement"] = text

    by_id.at["part-a-v2-2-118", "reviewer_note"] = (
        "QA 확인 완료: other_functional daily_frequency code 6의 '1일 5회'는 "
        "V2.2 taxonomy에 존재하는 canonical value이다."
    )
    by_id.at["part-a-v2-2-162", "reviewer_note"] = (
        "QA 확인 완료: V2.2 taxonomy에서는 '판토텐산, 비오틴'을 code 4로 유지하고 "
        "순서가 뒤집힌 중복 value는 제거했다."
    )
    return by_id.reset_index()


def build_candidate_set(taxonomy_path: Path = DEFAULT_TAXONOMY, reference_path: Path = DEFAULT_REFERENCE, seed: int = 42) -> pd.DataFrame:
    names, values = _load_taxonomy(taxonomy_path)
    reference = _reference_rows(reference_path)
    # Keep unique, known reviewed fixtures in DEV only. HOLDOUT must be unseen.
    unique_reference: list[dict[str, Any]] = []
    seen_reference: set[str] = set()
    for row in reference:
        key = _dedup_key(row["extra_requirement"])
        if key and key in seen_reference:
            continue
        seen_reference.add(key)
        unique_reference.append(row)
    generated = _new_rows(values, 50, seed) + _challenge_rows(values)
    rows = unique_reference[:100] + generated
    # Preserve a fixed review split, independent of generation order.
    records = []
    for index, row in enumerate(rows):
        split = "STANDARD" if index < 150 else "CHALLENGE"
        records.append(_record(row, f"part-a-v2-2-{index + 1:03d}", split, names.get(row["category_id"], "")))
    frame = pd.DataFrame(records, columns=REVIEW_COLUMNS)
    return _apply_quality_patches(frame)


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
        "## Candidate Partition", "",
        frame["evaluation_partition_candidate"].value_counts().sort_index().to_string(), "",
        "## Candidate Provenance", "",
        frame["candidate_origin"].value_counts().sort_index().to_string(), "",
        "## Parser Exposure", "",
        frame["parser_exposure"].value_counts().sort_index().to_string(), "",
        "## Provenance", "",
        "- Existing 200-row Legacy Gold: `NOT_FOUND`.",
        "- Existing 72.50% metric remains `LEGACY_EXPERIMENT_REFERENCE` and is not used as a baseline here.",
        f"- {reference_count} unique rows come from the tracked human-reviewed v042 evaluation fixture.",
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
    reference_count = int(frame["candidate_origin"].eq("EXISTING_REVIEWED_FIXTURE").sum())
    write_report(frame, args.report, reference_count)
    print({"status": "CANDIDATES_CREATED", "rows": len(frame), "standard": 150, "challenge": 50, "review_status": "PENDING_REVIEW"})


if __name__ == "__main__":
    main()
