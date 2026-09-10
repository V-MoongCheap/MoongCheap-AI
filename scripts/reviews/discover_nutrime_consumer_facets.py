"""Discover consumer-originated facet concepts from Nutrime reviews only."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pandas as pd


EXISTING_PATTERNS = {
    "ingredient_inclusion": [("성분", "ingredient_mentioned"), ("원료", "ingredient_mentioned"), ("함량", "ingredient_mentioned")],
    "intake_convenience": [("먹기 편", "convenient"), ("간편", "convenient"), ("챙겨", "convenient"), ("먹기 힘", "inconvenient"), ("복용하기 어렵", "inconvenient")],
    "odor": [("비린내", "fishy"), ("비린", "fishy"), ("냄새", "odor"), ("향", "odor")],
    "product_form": [("캡슐", "capsule"), ("알약", "tablet"), ("정제", "tablet"), ("액상", "liquid"), ("분말", "powder"), ("가루", "powder")],
    "swallowability": [("목넘김", "easy"), ("삼키기", "easy"), ("넘기기", "easy")],
    "tablet_size": [("알이 작", "small"), ("작은 알", "small"), ("알이 크", "large"), ("큰 알", "large")],
    "taste": [("맛", "taste"), ("쓴맛", "bitter"), ("쓴", "bitter")],
    "packaging": [("포장", "packaging"), ("스틱", "packaging"), ("휴대", "portable")],
}
EXISTING_VALUES = {
    "ingredient_inclusion": {"ingredient_mentioned"},
    "intake_convenience": {"convenient", "inconvenient"},
    "odor": {"fishy"},
    "product_form": {"capsule", "tablet", "liquid", "powder"},
    "swallowability": {"easy"},
    "tablet_size": {"small", "large"},
    "taste": {"bitter"},
    "packaging": {"packaging", "portable"},
}
NEW_VALUE_PATTERNS = {
    ("taste", "sweetness"): ["단맛", "달콤", "달다", "달아서"],
    ("taste", "aftertaste"): ["뒷맛", "끝맛", "잔향"],
    ("odor", "odorless"): ["냄새가 없", "냄새가 안", "무취"],
    ("product_form", "stick"): ["스틱형", "스틱 타입"],
}
NEW_FACET_PATTERNS = {
    "mixability": ["잘 섞", "잘 풀", "물에 녹", "타서", "흔들어"],
    "texture": ["식감", "걸쭉", "끈적", "목에 붙", "까끌", "거칠"],
    "dissolution": ["녹지 않", "안 녹", "덩어리", "가루가 남", "침전"],
    "opening_convenience": ["뜯기", "개봉", "뚜껑", "잘 안 열", "열기 어렵"],
    "storage_convenience": ["보관", "냉장", "상온", "보관하기"],
    "digestive_tolerance": ["속이 편", "속이 불편", "위에 부담", "더부룩"],
    "intake_frequency": ["하루 한", "하루에", "1일", "몇 번 먹", "번 먹"],
}
NON_FACET_PATTERNS = [
    "배송", "택배", "가격", "할인", "쿠폰", "프로모션", "판매자", "문의", "수량", "재고", "품절", "재구매", "선물", "브랜드",
]
MEDICAL_PATTERN = re.compile(r"효과|효능|치료|개선|완화|질환|증상|혈압|혈당|콜레스테롤|면역|관절|간 건강|눈 건강|피로 회복")


def _context(text: str, phrase: str, width: int = 100) -> str:
    index = text.find(phrase)
    if index < 0:
        return text[: width * 2]
    return text[max(0, index - width) : min(len(text), index + len(phrase) + width)].strip()


def _mapped_scope(row: pd.Series) -> str:
    return "HFF_MAPPED" if str(row.get("source_product_id", "")).strip() else "UNMAPPED_REFERENCE"


def _extract_review_rows(frame: pd.DataFrame) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for _, item in frame.iterrows():
        text = " ".join(str(item.get(column, "") or "") for column in ("review_title", "review_text")).strip()
        medical = bool(MEDICAL_PATTERN.search(text))
        found = False
        if medical:
            rows.append({**_base(item, text), "consumer_expression": MEDICAL_PATTERN.search(text).group(0), "normalized_concept": "medical_outcome", "existing_facet_match": "", "existing_value_match": "", "discovery_type": "SUBJECTIVE_MEDICAL_OUTCOME", "proposed_facet": "", "proposed_value": "", "evidence_sentence": _context(text, MEDICAL_PATTERN.search(text).group(0)), "confidence": "HIGH", "medical_outcome_flag": True})
            continue
        for (facet, value), phrases in NEW_VALUE_PATTERNS.items():
            for phrase in phrases:
                if phrase in text:
                    found = True
                    rows.append({**_base(item, text), "consumer_expression": phrase, "normalized_concept": f"{facet}:{value}", "existing_facet_match": facet, "existing_value_match": value if value in EXISTING_VALUES.get(facet, set()) else "", "discovery_type": "NEW_VALUE", "proposed_facet": facet, "proposed_value": value, "evidence_sentence": _context(text, phrase), "confidence": "MEDIUM", "medical_outcome_flag": False})
        for facet, phrases in NEW_FACET_PATTERNS.items():
            for phrase in phrases:
                if phrase in text:
                    found = True
                    rows.append({**_base(item, text), "consumer_expression": phrase, "normalized_concept": facet, "existing_facet_match": "", "existing_value_match": "", "discovery_type": "NEW_FACET_CANDIDATE", "proposed_facet": facet, "proposed_value": "", "evidence_sentence": _context(text, phrase), "confidence": "MEDIUM", "medical_outcome_flag": False})
        for facet, values in EXISTING_PATTERNS.items():
            for phrase, value in values:
                if phrase in text:
                    found = True
                    discovery = "EXISTING_FACET" if value in EXISTING_VALUES.get(facet, set()) else "NEW_ALIAS"
                    rows.append({**_base(item, text), "consumer_expression": phrase, "normalized_concept": f"{facet}:{value}", "existing_facet_match": facet, "existing_value_match": value, "discovery_type": discovery, "proposed_facet": facet if discovery == "NEW_ALIAS" else "", "proposed_value": value if discovery == "NEW_ALIAS" else "", "evidence_sentence": _context(text, phrase), "confidence": "HIGH", "medical_outcome_flag": False})
        if not found:
            expression = next((phrase for phrase in NON_FACET_PATTERNS if phrase in text), "")
            rows.append({**_base(item, text), "consumer_expression": expression, "normalized_concept": "non_facet", "existing_facet_match": "", "existing_value_match": "", "discovery_type": "NON_FACET", "proposed_facet": "", "proposed_value": "", "evidence_sentence": text[:220], "confidence": "LOW", "medical_outcome_flag": False})
    return rows


def _base(item: pd.Series, text: str) -> dict[str, object]:
    return {
        "review_id": str(item.get("source_review_id", "")),
        "product_id": str(item.get("source_product_id", "")),
        "product_name": str(item.get("product_name", "")),
        "service_category": "health-functional-food" if str(item.get("source_product_id", "")).strip() else "UNKNOWN",
        "review_text": str(item.get("review_text", "")),
        "mapping_scope": _mapped_scope(item),
    }


def _strength(review_count: int, product_count: int, expression_count: int) -> str:
    if product_count == 0:
        return "WEAK_CANDIDATE"
    if review_count >= 3 and product_count >= 2 and expression_count >= 2:
        return "STRONG_CANDIDATE"
    if review_count >= 2 or product_count >= 2:
        return "MODERATE_CANDIDATE"
    return "WEAK_CANDIDATE"


def _aggregate_new_facets(rows: pd.DataFrame, naver: pd.DataFrame, evidence: pd.DataFrame) -> pd.DataFrame:
    candidates = rows[rows["discovery_type"].eq("NEW_FACET_CANDIDATE")].copy()
    output: list[dict[str, object]] = []
    for concept, group in candidates.groupby("normalized_concept", sort=True):
        mapped = group[group["mapping_scope"].eq("HFF_MAPPED")]
        source = mapped if not mapped.empty else group
        examples = source["evidence_sentence"].drop_duplicates().head(5).tolist()
        examples += [""] * (5 - len(examples))
        phrase = str(group["consumer_expression"].iloc[0])
        naver_count = int(naver["review_text"].str.contains(re.escape(phrase), regex=True, na=False).sum()) if not naver.empty else 0
        seller_frame = evidence[evidence["source_type"].eq("SELLER_PRODUCT_EVIDENCE")] if not evidence.empty else pd.DataFrame()
        seller_text = seller_frame["text_raw"].astype(str) if not seller_frame.empty and "text_raw" in seller_frame else pd.Series(dtype=str)
        seller_count = int(seller_text.str.contains(re.escape(phrase), regex=True, na=False).sum()) if not seller_text.empty else 0
        product_count = int(source["product_id"].replace("", pd.NA).dropna().nunique())
        category_count = int(source.loc[source["mapping_scope"].eq("HFF_MAPPED"), "service_category"].replace("", pd.NA).dropna().nunique())
        strength = _strength(int(len(source)), product_count, int(group["consumer_expression"].nunique()))
        output.append({
            "proposed_facet": concept,
            "strength": strength,
            "review_count": int(len(source)),
            "unique_product_count": product_count,
            "unique_category_count": category_count,
            "unique_expression_count": int(group["consumer_expression"].nunique()),
            "representative_examples": " || ".join(examples),
            "existing_facet_similarity": "LOW / no existing facet pattern matched",
            # The available product corpus has no verified crosswalk to Nutrime IDs.
            "product_verifiability": "NOT_VERIFIABLE",
            "seller_support": "SUPPORTED_SELLER_DATA" if seller_count else "NO_SELLER_SUPPORT",
            "naver_expression_support": "KOREAN_GENERAL_CONSUMER_EXPRESSION_SUPPORT" if naver_count else "NO_REFERENCE_MATCH",
            "naver_expression_count": naver_count,
            "reviewer_decision": "PENDING_REVIEW",
            "reviewer_note": "Candidate only; no Taxonomy change. Review-only evidence takes priority over unverified product assumptions.",
        })
    return pd.DataFrame(output)


def build_report(rows: pd.DataFrame, candidates: pd.DataFrame, output: Path, raw_count: int, mapped_count: int) -> None:
    counts = rows["discovery_type"].value_counts().to_dict()
    strength = candidates["strength"].value_counts().to_dict() if not candidates.empty else {}
    lines = [
        "# Nutrime Consumer Facet Discovery",
        "",
        "실제 Nutrime 건강기능식품 Review에서 기존 Taxonomy로 설명되지 않는 소비자 경험 후보를 탐색한 결과다. 기존 Taxonomy와 Alias 66개는 변경하지 않았다.",
        "",
        "## Scope",
        f"- analyzed raw reviews: {raw_count}",
        f"- primary HFF-mapped reviews: {mapped_count}",
        f"- unmapped reference reviews: {raw_count - mapped_count}",
        "- Naver Corpus: 후보 발견 후 약한 표현 참고용으로만 검색",
        "",
        "## Discovery Type Counts",
        "| type | row count |",
        "|---|---:|",
    ]
    for kind in ("EXISTING_FACET", "NEW_VALUE", "NEW_ALIAS", "NEW_FACET_CANDIDATE", "NON_FACET", "SUBJECTIVE_MEDICAL_OUTCOME"):
        lines.append(f"| {kind} | {int(counts.get(kind, 0))} |")
    lines += [
        "",
        "## New Facet Candidate Strength",
        "| strength | count |",
        "|---|---:|",
        f"| STRONG_CANDIDATE | {int(strength.get('STRONG_CANDIDATE', 0))} |",
        f"| MODERATE_CANDIDATE | {int(strength.get('MODERATE_CANDIDATE', 0))} |",
        f"| WEAK_CANDIDATE | {int(strength.get('WEAK_CANDIDATE', 0))} |",
        "",
        "## Candidate Review",
    ]
    if candidates.empty:
        lines.append("신규 Facet Candidate가 발견되지 않았다.")
    else:
        lines += ["| proposed facet | strength | reviews | products | categories | expressions | product | seller | Naver reference |", "|---|---|---:|---:|---:|---:|---|---|---|"]
        for row in candidates.itertuples(index=False):
            lines.append(f"| {row.proposed_facet} | {row.strength} | {row.review_count} | {row.unique_product_count} | {row.unique_category_count} | {row.unique_expression_count} | {row.product_verifiability} | {row.seller_support} | {row.naver_expression_support} ({row.naver_expression_count}) |")
    lines += [
        "",
        "## Interpretation",
        "- `EXISTING_FACET`와 `NEW_VALUE`/`NEW_ALIAS`는 신규 Facet으로 승격하지 않는다.",
        "- 배송·가격·프로모션·판매자 응대·수량·재구매·단순 만족 표현은 Non-Facet으로 분리한다.",
        "- 의료 효능·질병 개선 표현은 `SUBJECTIVE_MEDICAL_OUTCOME`으로 별도 분리한다.",
        "- Product/Seller에 없는 소비자 체감 특성도 `REVIEW_ONLY` 후보로 보존할 수 있으나 자동 승인하지 않는다.",
        "- 모든 신규 후보의 reviewer_decision은 `PENDING_REVIEW`다.",
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("data/processed/reviews/nutrime/nutrime_consumer_facet_discovery.csv"))
    parser.add_argument("--human-review", type=Path, default=Path("data/review/model1_new_facet_human_review.csv"))
    parser.add_argument("--report", type=Path, default=Path("reports/nutrime_consumer_facet_discovery.md"))
    parser.add_argument("--naver", type=Path)
    parser.add_argument("--seller-evidence", type=Path)
    args = parser.parse_args()
    with args.input.open(encoding="utf-8") as handle:
        frame = pd.DataFrame(json.loads(line) for line in handle)
    rows = pd.DataFrame(_extract_review_rows(frame))
    naver = pd.read_csv(args.naver, sep="\t", header=None, names=["rating", "review_text"], encoding="utf-8", dtype=str) if args.naver and args.naver.exists() else pd.DataFrame()
    evidence = pd.read_parquet(args.seller_evidence) if args.seller_evidence and args.seller_evidence.exists() else pd.DataFrame()
    candidates = _aggregate_new_facets(rows, naver, evidence)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    rows.to_csv(args.output, index=False, encoding="utf-8-sig")
    args.human_review.parent.mkdir(parents=True, exist_ok=True)
    candidates.to_csv(args.human_review, index=False, encoding="utf-8-sig")
    mapped_count = int(frame["source_product_id"].astype(str).str.strip().ne("").sum())
    build_report(rows, candidates, args.report, len(frame), mapped_count)
    new_rows = rows[rows.discovery_type.eq("NEW_FACET_CANDIDATE")]
    print(json.dumps({"status": "COMPLETED", "raw_reviews": len(frame), "mapped_reviews": mapped_count, "analysis_rows": len(rows), "new_facet_candidate_expression_count": int(new_rows.consumer_expression.nunique()), "new_facet_candidate_rows": int(len(new_rows)), "unique_new_facet_count": len(candidates), "medical_review_count": int(rows.loc[rows.discovery_type.eq("SUBJECTIVE_MEDICAL_OUTCOME"), "review_id"].nunique()), "discovery_counts": rows.discovery_type.value_counts().to_dict(), "strength_counts": candidates.strength.value_counts().to_dict() if not candidates.empty else {}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
