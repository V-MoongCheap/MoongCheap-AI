"""Run final QA for the five existing Nutrime facet candidates.

This script intentionally does not discover new candidates. It reads the
existing discovery output and enriches the human-review artifacts with
product-field, taxonomy, mapping, and count QA.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


CANDIDATES = (
    "intake_frequency",
    "opening_convenience",
    "storage_convenience",
    "digestive_tolerance",
    "mixability",
)

TAXONOMY_RELATIONS = {
    "intake_frequency": "VALUE_OF_EXISTING_FACET",
    "opening_convenience": "RELATED_BUT_DISTINCT",
    "storage_convenience": "RELATED_BUT_DISTINCT",
    "digestive_tolerance": "UNRESOLVED",
    "mixability": "VALUE_OF_EXISTING_FACET",
}

REVIEW_ACTIONS = {
    "VALUE_OF_EXISTING_FACET": "REVIEW_FOR_VALUE",
    "RELATED_BUT_DISTINCT": "REVIEW_AS_NEW_FACET",
    "UNRESOLVED": "REVIEW_AFTER_SOURCE_CHECK",
}


def _read_jsonl(path: Path) -> pd.DataFrame:
    with path.open(encoding="utf-8") as handle:
        return pd.DataFrame(json.loads(line) for line in handle if line.strip())


def _product_field_qa(path: Path) -> dict[str, object]:
    if not path.exists():
        return {
            "available": False,
            "rows": 0,
            "daily_frequency_rows": 0,
            "unique_products": 0,
            "reason": "PRODUCT_CORPUS_NOT_FOUND",
        }
    frame = pd.read_csv(path, dtype=str, encoding="utf-8-sig")
    frequency = frame.get("daily_frequency_candidate", pd.Series(dtype=str)).fillna("").str.strip()
    ids = frame.loc[frequency.ne(""), "source_product_id"].fillna("").astype(str).str.strip()
    return {
        "available": True,
        "rows": int(len(frame)),
        "daily_frequency_rows": int(frequency.ne("").sum()),
        "unique_products": int(ids[ids.ne("")].nunique()),
        "reason": "FIELD_AVAILABLE_BUT_NUTRIME_PRODUCT_CROSSWALK_NOT_VERIFIED",
    }


def _examples(group: pd.DataFrame, count: int = 5) -> str:
    values = group["evidence_sentence"].fillna("").drop_duplicates().tolist()
    values = [value for value in values if value]
    return " || ".join(values[:count])


def _mixability_details(raw: pd.DataFrame, discovery: pd.DataFrame) -> pd.DataFrame:
    ids = set(discovery.loc[discovery["proposed_facet"].eq("mixability"), "review_id"].astype(str))
    rows = raw[raw["source_review_id"].astype(str).isin(ids)].copy()
    details = []
    for _, row in rows.sort_values("source_review_id").iterrows():
        product_id = str(row.get("source_product_id", "") or "").strip()
        mapped = bool(product_id)
        details.append(
            {
                "review_id": str(row.get("source_review_id", "")),
                "full_review_text": str(row.get("review_text", "") or ""),
                "source_product_id": product_id,
                "source_product_name": str(row.get("product_name", "") or ""),
                "mapping_status": "MAPPED_BY_SOURCE_PRODUCT_ID" if mapped else "UNMAPPED",
                "hff_status": "HFF_CONFIRMED_BY_SOURCE_MAPPING" if mapped else "HFF_UNCERTAIN_UNMAPPED",
                "mapping_failure_reason": "" if mapped else "SOURCE_PRODUCT_ID_EMPTY; PRODUCT_AND_CATEGORY_CANNOT_BE_VERIFIED",
            }
        )
    return pd.DataFrame(details)


def _discovery_counts(discovery: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for kind, group in discovery.groupby("discovery_type", sort=True):
        rows.append(
            {
                "discovery_type": kind,
                "analysis_row_count": int(len(group)),
                "unique_review_count": int(group["review_id"].astype(str).nunique()),
            }
        )
    return pd.DataFrame(rows).sort_values("discovery_type")


def build_report(
    output: Path,
    raw_count: int,
    discovery: pd.DataFrame,
    candidates: pd.DataFrame,
    product_qa: dict[str, object],
    mixability_path: Path,
) -> None:
    counts = _discovery_counts(discovery)
    lines = [
        "# Nutrime Consumer Facet Discovery 최종 QA",
        "",
        "기존 Discovery 결과를 재탐색하지 않고 Human Review 전 검증만 수행한 보고서다.",
        "Taxonomy와 Alias 66개는 수정하지 않았다.",
        "",
        "## Count Definition",
        f"- TOTAL_UNIQUE_REVIEWS_ANALYZED: {raw_count}",
        f"- EXTRACTED_ANALYSIS_ROWS: {len(discovery)}",
        "- One review can produce multiple expressions, so discovery-type analysis row totals can exceed 423.",
        "",
        "## Discovery Type Counts",
        "| discovery_type | analysis_row_count | unique_review_count |",
        "|---|---:|---:|",
    ]
    for row in counts.itertuples(index=False):
        lines.append(f"| {row.discovery_type} | {row.analysis_row_count} | {row.unique_review_count} |")
    lines += [
        "",
        "## Intake Frequency Product Verification",
        f"- Product corpus rows: {product_qa['rows']}",
        f"- Rows with daily_frequency_candidate: {product_qa['daily_frequency_rows']}",
        f"- Unique products with the field: {product_qa['unique_products']}",
        "- Product source fields: intake_method, 섭취방법, daily_frequency_candidate, amount_per_intake_candidate, dose_unit_candidate.",
        "- Conclusion: the related fields exist in the Product Corpus. Nutrime remains NOT_VERIFIABLE because no verified crosswalk exists between Nutrime source_product_id and the MFDS Product Corpus; this is not a missing verifier field.",
        "- Individual Nutrime product verification therefore remains unresolved; only Product Corpus field availability is verified.",
        "",
        "## Candidate QA",
        "| proposed_facet | strength | analysis rows | unique reviews | products | categories | taxonomy relation | review action | product verifiability |",
        "|---|---|---:|---:|---:|---:|---|---|---|",
    ]
    for row in candidates.itertuples(index=False):
        lines.append(
            f"| {row.proposed_facet} | {row.strength} | {row.analysis_row_count} | {row.unique_review_count} | {row.unique_product_count} | {row.unique_category_count} | {row.existing_taxonomy_relation} | {row.recommended_review_action} | {row.product_verifiability} |"
        )
    lines += [
        "",
        "## Digestive Tolerance",
        "- Classification: CONSUMER_USAGE_EXPERIENCE",
        "- The source text describes an individual experience after intake. It does not provide sufficient basis for a disease outcome or an explicit adverse-reaction classification.",
        "- It remains a WEAK_CANDIDATE and is not eligible for automatic Facet approval.",
        "",
        "## Mixability Mapping Detail",
        f"- 상세 파일: `{mixability_path.as_posix()}`",
        "- All three rows have an empty source_product_id. This is an unmapped input record, not evidence that Product information was lost in the pipeline.",
        "- HFF status is therefore not confirmed from source mapping and is marked HFF_UNCERTAIN_UNMAPPED.",
        "",
        "## Human Review Rule",
        "- reviewer_decision remains PENDING_REVIEW for every candidate.",
        "- recommended_review_action is a review hint, not an automatic approval.",
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> dict[str, object]:
    raw = _read_jsonl(args.raw)
    discovery = pd.read_csv(args.discovery, dtype=str, encoding="utf-8-sig").fillna("")
    candidates = pd.read_csv(args.human_review, dtype=str, encoding="utf-8-sig").fillna("")
    candidates = candidates[candidates["proposed_facet"].isin(CANDIDATES)].copy()
    product_qa = _product_field_qa(args.product_fields)

    # Existing discovery rows are the source of truth; this pass only adds QA columns.
    records = []
    for _, candidate in candidates.iterrows():
        facet = candidate["proposed_facet"]
        group = discovery[discovery["proposed_facet"].eq(facet)]
        relation = TAXONOMY_RELATIONS[facet]
        verifiability = candidate.get("product_verifiability", "NOT_VERIFIABLE")
        note = ""
        if facet == "intake_frequency":
            verifiability = "NOT_VERIFIABLE_NUTRIME_CROSSWALK_MISSING_FIELD_AVAILABLE"
            note = "Product Corpus에는 섭취방법/daily_frequency 필드가 있으나 Nutrime 상품과의 검증된 crosswalk가 없어 개별 검증 불가."
        elif facet == "digestive_tolerance":
            note = "분류: CONSUMER_USAGE_EXPERIENCE; 단일 상품 1건으로 약한 후보이며 자동 승인하지 않음."
        elif facet == "mixability":
            note = "3건 모두 source_product_id가 비어 있는 실제 미매핑 Review이며 Pipeline에서 Product 정보가 유실된 사례로 보지 않음."
        records.append(
            {
                "proposed_facet": facet,
                "strength": candidate.get("strength", ""),
                "analysis_row_count": int(len(group)),
                "unique_review_count": int(group["review_id"].astype(str).nunique()),
                "unique_product_count": int(group.loc[group["product_id"].ne(""), "product_id"].nunique()),
                "unique_category_count": int(group.loc[group["service_category"].ne("UNKNOWN"), "service_category"].nunique()),
                "representative_examples": _examples(group),
                "product_verifiability": verifiability,
                "seller_support": candidate.get("seller_support", ""),
                "naver_expression_support": candidate.get("naver_expression_support", ""),
                "existing_taxonomy_relation": relation,
                "recommended_review_action": REVIEW_ACTIONS[relation],
                "reviewer_decision": "PENDING_REVIEW",
                "reviewer_note": note,
                "existing_facet_similarity": candidate.get("existing_facet_similarity", ""),
                "naver_expression_count": candidate.get("naver_expression_count", ""),
            }
        )
    reviewed = pd.DataFrame(records).sort_values("proposed_facet")
    args.human_review.parent.mkdir(parents=True, exist_ok=True)
    reviewed.to_csv(args.human_review, index=False, encoding="utf-8-sig")

    details = _mixability_details(raw, discovery)
    args.mixability_details.parent.mkdir(parents=True, exist_ok=True)
    details.to_csv(args.mixability_details, index=False, encoding="utf-8-sig")
    build_report(args.report, len(raw), discovery, reviewed, product_qa, args.mixability_details)

    index = args.index
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text(
        "# Model 1 Human Review Index\n\n"
        "## A. New Facet Candidates — 5\n\n"
        "QA sheet: `data/review/model1_new_facet_human_review.csv`\n\n"
        "상세 Mixability 원문: `data/review/model1_mixability_review_details.csv`\n\n"
        "최종 QA Report: `reports/nutrime_consumer_facet_discovery.md`\n\n"
        "## B. Alias Candidates — 66\n\n"
        "Alias sheet: `data/review/model1_alias_human_review.csv`\n\n"
        "Alias 검수 안내: `reports/model1_alias_human_review_guide.md`\n\n"
        "Alias와 New Facet은 서로 다른 검수 대상이며, 자동 병합하거나 Taxonomy에 자동 반영하지 않는다.\n",
        encoding="utf-8",
    )
    return {
        "status": "COMPLETED",
        "total_unique_reviews_analyzed": int(len(raw)),
        "extracted_analysis_rows": int(len(discovery)),
        "mixability_detail_rows": int(len(details)),
        "product_daily_frequency_rows": int(product_qa["daily_frequency_rows"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", type=Path, default=Path("data/raw/reviews/nutrime/nutrime_reviews_500_20260909.jsonl"))
    parser.add_argument("--discovery", type=Path, default=Path("data/processed/reviews/nutrime/nutrime_consumer_facet_discovery.csv"))
    parser.add_argument("--human-review", type=Path, default=Path("data/review/model1_new_facet_human_review.csv"))
    parser.add_argument("--product-fields", type=Path, default=Path("../data/processed/health_foundation_v1/intake_method_structured_v1.csv"))
    parser.add_argument("--mixability-details", type=Path, default=Path("data/review/model1_mixability_review_details.csv"))
    parser.add_argument("--report", type=Path, default=Path("reports/nutrime_consumer_facet_discovery.md"))
    parser.add_argument("--index", type=Path, default=Path("reports/model1_human_review_index.md"))
    args = parser.parse_args()
    print(json.dumps(run(args), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
