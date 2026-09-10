"""Prepare a spreadsheet-friendly human review sheet for expression candidates."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pandas as pd


CANONICAL_NAMES = {
    "ingredient_inclusion": "기능성 성분 포함",
    "intake_convenience": "섭취 편의성",
    "odor": "냄새",
    "packaging": "포장",
    "product_form": "제형",
    "swallowability": "목넘김",
    "tablet_size": "정제 크기",
    "taste": "맛",
}
MEDICAL = re.compile(r"효과|효능|치료|개선|완화|질환|증상|혈압|혈당|콜레스테롤|면역|관절|간건강|눈건강")
PRODUCT_CONTEXT = re.compile(r"브랜드|상품명|제품명|모델명|상품번호|\b[A-Z]{2,}\b|\d{2,}")
GENERIC_EXPRESSIONS = {"맛이", "맛은", "포장이", "포장도", "향이", "사이즈가", "성분", "냄새"}
SIMPLE_SENTIMENT = re.compile(r"^(좋|좋아요|최고|만족|별로|싫|나쁨|괜찮|추천)[가-힣]*$")


def _risk_flags(expression: str, examples: list[str]) -> list[str]:
    joined = " ".join(examples)
    flags: list[str] = []
    if len(expression.replace(" ", "")) <= 3:
        flags.append("TOO_SHORT")
    if expression in GENERIC_EXPRESSIONS or SIMPLE_SENTIMENT.match(expression):
        flags.append("TOO_GENERIC")
    if PRODUCT_CONTEXT.search(expression) or PRODUCT_CONTEXT.search(joined):
        flags.append("PRODUCT_OR_BRAND_CONTEXT")
    if MEDICAL.search(expression) or MEDICAL.search(joined):
        flags.append("MEDICAL_OUTCOME")
    if len(expression.replace(" ", "")) <= 4 or expression in {"향이", "맛이", "맛은", "포장이", "사이즈가"}:
        flags.append("CONTEXT_AMBIGUOUS")
    return sorted(set(flags))


def _load_raw(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, sep="\t", header=None, names=["rating", "review_text"], encoding="utf-8", dtype=str, keep_default_na=False)


def _rating_distribution(values: pd.Series) -> str:
    counts = values.value_counts().reindex(["1", "2", "3", "4", "5"], fill_value=0)
    return "|".join(f"{rating}:{int(counts[rating])}" for rating in counts.index)


def build_sheet(candidates: pd.DataFrame, raw: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    rows: list[dict[str, object]] = []
    conflict_groups = candidates.groupby(candidates["candidate_expression"].astype(str).str.strip())["facet_id"].nunique()
    for item in candidates.itertuples(index=False):
        expression = str(item.candidate_expression).strip()
        matches = raw[raw["review_text"].str.contains(re.escape(expression), regex=True, na=False)]
        examples = matches["review_text"].drop_duplicates().head(5).tolist()
        while len(examples) < 5:
            examples.append("")
        flags = _risk_flags(expression, examples)
        conflict = "CROSS_FACET_CONFLICT" if int(conflict_groups.get(expression, 0)) > 1 else ""
        note_parts = list(flags)
        if conflict:
            note_parts.append(conflict)
        rows.append(
            {
                "category_id": "NOT_AVAILABLE_SOURCE_HAS_NO_CATEGORY",
                "category_name": "NOT_AVAILABLE_SOURCE_HAS_NO_CATEGORY",
                "facet_id": item.facet_id,
                "canonical_facet_name": CANONICAL_NAMES.get(str(item.facet_id), str(item.facet_id)),
                "value_candidate": item.value_candidate,
                "corrected_value_candidate": "",
                "seed_expression": item.seed_expression,
                "candidate_expression": expression,
                "occurrence_count": int(item.occurrence_count),
                "semantic_similarity": float(item.semantic_similarity),
                "example_sentence_1": examples[0],
                "example_sentence_2": examples[1],
                "example_sentence_3": examples[2],
                "example_sentence_4": examples[3],
                "example_sentence_5": examples[4],
                "naver_rating_distribution": _rating_distribution(matches["rating"]),
                "source_type": "KOREAN_SHOPPING_REVIEW_EXPRESSION_REFERENCE",
                "current_status": item.reviewer_decision,
                "reviewer_decision": "PENDING_REVIEW",
                "reviewer_note": ";".join(note_parts),
                "risk_flags": "|".join(flags),
                "conflict_status": conflict,
                "review_priority": "HIGH" if conflict or "MEDICAL_OUTCOME" in flags else "NORMAL",
            }
        )
    sheet = pd.DataFrame(rows)
    sheet = sheet.sort_values(["review_priority", "occurrence_count", "semantic_similarity"], ascending=[True, False, False], kind="stable").reset_index(drop=True)
    sheet.insert(0, "review_order", range(1, len(sheet) + 1))
    stats = {
        "candidate_count": len(sheet),
        "facet_type_count": int(sheet["facet_id"].nunique()),
        "review_supported_combination_count": int(candidates[["facet_id", "value_candidate"]].drop_duplicates().shape[0]),
        "category_facet_combination_count": 0,
        "cross_facet_conflict_count": int(sheet["conflict_status"].ne("").sum()),
        "generic_risk_count": int(sheet["risk_flags"].str.contains("TOO_GENERIC", na=False).sum()),
        "medical_risk_count": int(sheet["risk_flags"].str.contains("MEDICAL_OUTCOME", na=False).sum()),
        "needs_review_count": int(sheet["reviewer_decision"].eq("PENDING_REVIEW").sum()),
    }
    return sheet, stats


def build_report(sheet: pd.DataFrame, stats: dict[str, int], output: Path, input_path: Path) -> None:
    lines = [
        "# Model 1 Alias Human Review Guide",
        "",
        "이 문서는 Naver Shopping Expression Reference에서 생성된 Alias 후보를 사람이 검수하기 위한 작업지다. 후보를 자동 승인하지 않으며 기존 Taxonomy에도 반영하지 않는다.",
        "",
        "## Input and Review Policy",
        f"- input: `{input_path}`",
        f"- total Alias Candidate: {stats['candidate_count']}",
        f"- source_type: `KOREAN_SHOPPING_REVIEW_EXPRESSION_REFERENCE`",
        "- category_id/category_name: 원본에 Category 정보가 없어 `NOT_AVAILABLE_SOURCE_HAS_NO_CATEGORY`로 기록",
        "- reviewer_decision initial value: `PENDING_REVIEW`",
        "- `corrected_value_candidate` is reserved for a human-corrected standard value; the generated `value_candidate` is preserved.",
        "- 승인값은 별도 Apply 단계에서만 Taxonomy에 병합 가능",
        "",
        "## Structure Clarification",
        f"- 실제 Facet 종류 수: {stats['facet_type_count']}",
        f"- Review-supported 조합 수: {stats['review_supported_combination_count']}",
        "- 이 14개 조합은 Category-Facet 조합이 아니다.",
        "- 기존 `facet_review_queue_v2.csv`에서 Review source count가 있는 행의 `facet_candidate + value_candidate` 고유 조합 수다.",
        "- Category 정보가 없는 Naver Corpus를 사용했으므로 식별 가능한 Category-Facet 조합 수는 0이다.",
        "",
        "## Review Columns",
        "- `example_sentence_1`~`example_sentence_5`: 후보 표현이 실제로 포함된 원문 예시",
        "- `naver_rating_distribution`: 별점별 문장 수. HFF 선호도나 HFF 중요도 지표가 아님",
        "- `risk_flags`: TOO_SHORT, TOO_GENERIC, PRODUCT_OR_BRAND_CONTEXT, MEDICAL_OUTCOME, CONTEXT_AMBIGUOUS",
        "- `CROSS_FACET_CONFLICT`: 동일 표현이 둘 이상의 Facet에 걸린 후보",
        "",
        "## Summary",
        f"- Cross-facet conflict: {stats['cross_facet_conflict_count']}",
        f"- Generic risk: {stats['generic_risk_count']}",
        f"- Medical risk: {stats['medical_risk_count']}",
        f"- Human review pending: {stats['needs_review_count']}",
        "",
        "## Allowed Reviewer Decisions",
        "`APPROVE_ALIAS`, `REJECT_TOO_GENERIC`, `REJECT_DIFFERENT_MEANING`, `REJECT_PRODUCT_SPECIFIC`, `REJECT_NON_HFF_CONTEXT`, `REJECT_MEDICAL_OUTCOME`, `NEEDS_REVIEW`",
        "",
        "## Review Order",
        "Occurrence count와 semantic similarity가 높은 후보를 우선 배치했다. Conflict와 Medical risk는 우선순위를 높여 먼저 확인하도록 했다.",
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("data/review/model1_alias_human_review.csv"))
    parser.add_argument("--report", type=Path, default=Path("reports/model1_alias_human_review_guide.md"))
    args = parser.parse_args()
    candidates = pd.read_csv(args.input, dtype=str).fillna("")
    candidates["occurrence_count"] = pd.to_numeric(candidates["occurrence_count"], errors="coerce").fillna(0).astype(int)
    candidates["semantic_similarity"] = pd.to_numeric(candidates["semantic_similarity"], errors="coerce").fillna(0.0)
    raw = _load_raw(args.raw)
    sheet, stats = build_sheet(candidates, raw)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    sheet.to_csv(args.output, index=False, encoding="utf-8-sig")
    build_report(sheet, stats, args.report, args.input)
    print(json.dumps({"status": "COMPLETED", **stats, "output": str(args.output), "report": str(args.report)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
