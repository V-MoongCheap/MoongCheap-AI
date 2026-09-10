"""Build service-category coverage and product-concentration metrics for review snapshots."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pandas as pd

from moongcheap_ai.data_foundation.facet_evidence import build_review_evidence


THRESHOLDS = ((0, "CRITICAL"), (49, "VERY_LOW"), (149, "LOW"), (299, "MODERATE"))


def _norm(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def _band(count: int) -> str:
    for limit, label in THRESHOLDS:
        if count <= limit:
            return label
    return "GOOD"


def _load_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def build_report(
    review_paths: list[Path],
    mapping_path: Path,
    category_path: Path,
    evidence_path: Path | None,
    output: Path,
    analysis_max_reviews_per_product: int | None = None,
) -> dict[str, object]:
    reviews: list[dict[str, object]] = []
    for path in review_paths:
        source = path.parent.name
        reviews.extend({**row, "_source": source} for row in _load_jsonl(path))

    mapping = pd.read_csv(mapping_path, dtype=str).fillna("") if mapping_path.exists() else pd.DataFrame()
    categories = pd.read_csv(category_path, dtype=str).fillna("") if category_path.exists() else pd.DataFrame()
    # Review-store IDs and MFDS IDs are separate namespaces.  Do not join them
    # by numeric coincidence; an explicit crosswalk is required for ID mapping.
    id_map: dict[str, str] = {}
    name_map = dict(zip(mapping.get("product_name", pd.Series(dtype=str)).map(_norm), mapping.get("service_category_name", pd.Series(dtype=str))))

    rows = []
    for item in reviews:
        product_id = str(item.get("source_product_id") or "")
        product_name = str(item.get("product_name") or "")
        category = id_map.get(product_id) or name_map.get(_norm(product_name)) or "UNMAPPED_REVIEW_PRODUCT"
        rows.append({"source": str(item.get("_source") or "unknown"), "review_id": str(item.get("source_review_id") or ""), "product_id": product_id, "product_name": product_name, "category": category, "mapped": category != "UNMAPPED_REVIEW_PRODUCT"})
    review_frame = pd.DataFrame(rows)
    analysis_review_count = len(review_frame)
    if analysis_max_reviews_per_product is not None and not review_frame.empty:
        seen_products: dict[tuple[str, str], int] = {}
        analysis_review_count = 0
        for item in review_frame.itertuples(index=False):
            key = (str(item.source), str(item.product_id))
            if not item.product_id or seen_products.get(key, 0) < analysis_max_reviews_per_product:
                analysis_review_count += 1
                if item.product_id:
                    seen_products[key] = seen_products.get(key, 0) + 1

    category_names = list(categories.get("category_name", pd.Series(dtype=str))) if not categories.empty else []
    category_names = list(dict.fromkeys([name for name in category_names if name]))
    if "UNMAPPED_REVIEW_PRODUCT" in review_frame.get("category", pd.Series(dtype=str)).values:
        category_names.append("UNMAPPED_REVIEW_PRODUCT")
    evidence = pd.read_parquet(evidence_path) if evidence_path and evidence_path.exists() else pd.DataFrame()
    evidence_counts: dict[str, int] = {}
    if not evidence.empty and not review_frame.empty:
        mapped_products = review_frame[review_frame["mapped"] & review_frame["product_id"].ne("")].drop_duplicates("product_id")
        product_categories = dict(zip(mapped_products["product_id"], mapped_products["category"]))
        review_evidence = evidence[evidence.get("source_type", "").eq("KOREAN_HFF_RAW_REVIEW")].copy()
        review_evidence["category_from_mapping"] = review_evidence.get("product_ref", "").astype(str).map(product_categories)
        evidence_counts = review_evidence.dropna(subset=["category_from_mapping"]).groupby("category_from_mapping").size().to_dict()

    output_rows = []
    for category in category_names:
        subset = review_frame[review_frame["category"].eq(category)] if not review_frame.empty else pd.DataFrame()
        products = subset["product_id"].replace("", pd.NA).dropna().nunique() if not subset.empty else 0
        output_rows.append({"service_category_name": category, "review_count": len(subset), "unique_product_count": products, "unique_source_count": subset["source"].nunique() if not subset.empty else 0, "mapped_review_count": int(subset["mapped"].sum()) if not subset.empty else 0, "facet_evidence_count": int(evidence_counts.get(category, 0)), "coverage_band": _band(len(subset))})
    coverage = pd.DataFrame(output_rows)

    concentration_rows = []
    if not review_frame.empty:
        for (source, category), subset in review_frame.groupby(["source", "category"]):
            counts = subset.groupby("product_id").size().sort_values(ascending=False)
            total = len(subset)
            concentration_rows.append({"source": source, "service_category_name": category, "total_reviews": total, "unique_products": int(len(counts)), "reviews_per_product_median": float(counts.median()) if len(counts) else 0, "reviews_per_product_max": int(counts.max()) if len(counts) else 0, "top_1_product_share": float(counts.head(1).sum() / total) if total else 0, "top_5_product_share": float(counts.head(5).sum() / total) if total else 0, "top_10_product_share": float(counts.head(10).sum() / total) if total else 0})
    concentration = pd.DataFrame(concentration_rows)

    output.parent.mkdir(parents=True, exist_ok=True)
    coverage.to_csv(output.with_suffix(".csv"), index=False, encoding="utf-8-sig")
    lines = ["# 한국 건강기능식품 Review Category Coverage", "", "기준: Raw review snapshot을 보존한 상태에서 Product/Category 연결이 확인된 건만 매핑 카테고리에 집계한다. 연결되지 않은 상품은 별도 행으로 남긴다.", "", f"- 총 Raw Review: {len(review_frame)}", f"- Analysis Review: {analysis_review_count} (상품별 상한: {analysis_max_reviews_per_product or '없음'})", f"- 매핑 성공 Review: {int(review_frame['mapped'].sum()) if not review_frame.empty else 0}", f"- Unique Product: {review_frame['product_id'].replace('', pd.NA).dropna().nunique() if not review_frame.empty else 0}", f"- Review Source 수: {review_frame['source'].nunique() if not review_frame.empty else 0}", "", "## Category Coverage", "| Service Category | Review | Unique Product | Source | Mapped Review | Facet Evidence | Band |", "|---|---:|---:|---:|---:|---:|---|"]
    for row in output_rows:
        lines.append(f"| {row['service_category_name']} | {row['review_count']} | {row['unique_product_count']} | {row['unique_source_count']} | {row['mapped_review_count']} | {row['facet_evidence_count']} | {row['coverage_band']} |")
    lines += ["", "## Product Concentration", "| Source | Category | Reviews | Products | Median/Product | Max/Product | Top 1 | Top 5 | Top 10 |", "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for row in concentration_rows:
        lines.append(f"| {row['source']} | {row['service_category_name']} | {row['total_reviews']} | {row['unique_products']} | {row['reviews_per_product_median']:.1f} | {row['reviews_per_product_max']} | {row['top_1_product_share']:.2%} | {row['top_5_product_share']:.2%} | {row['top_10_product_share']:.2%} |")
    lines += ["", "## 해석", "- CRITICAL/VERY_LOW 카테고리는 다음 Review Source 탐색 우선순위로만 사용하며 Taxonomy 승인 기준으로 사용하지 않는다.", "- Product ID 체계가 MFDS mapping과 다르면 자동 결합하지 않는다. 현재 뉴트리미처럼 별도 쇼핑몰 ID만 가진 Review는 UNMAPPED_REVIEW_PRODUCT로 보존한다.", "- 한 상품에 리뷰가 집중되는 경우 Consumer Salience를 전체 Category 대표값으로 확대 해석하지 않는다."]
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"review_count": len(review_frame), "mapped_review_count": int(review_frame["mapped"].sum()) if not review_frame.empty else 0, "unique_product_count": int(review_frame["product_id"].replace("", pd.NA).dropna().nunique()) if not review_frame.empty else 0, "source_count": int(review_frame["source"].nunique()) if not review_frame.empty else 0, "category_count": len(output_rows), "good_category_count": sum(row["coverage_band"] == "GOOD" for row in output_rows)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--review", action="append", type=Path, required=True)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--categories", type=Path, required=True)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--analysis-max-reviews-per-product", type=int, default=None)
    parser.add_argument("--output", type=Path, default=Path("reports/hff_review_category_coverage.md"))
    args = parser.parse_args()
    print(build_report(args.review, args.mapping, args.categories, args.evidence, args.output, args.analysis_max_reviews_per_product))
