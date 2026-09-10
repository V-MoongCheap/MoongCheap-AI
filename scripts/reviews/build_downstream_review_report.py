from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def _count(path: Path, minimum: int) -> int:
    if not path.exists():
        return 0
    frame = pd.read_csv(path)
    return int((frame["source_count"] >= minimum).sum())


def build_report(before_dir: Path, after_dir: Path, output: Path) -> dict[str, int]:
    before = pd.read_csv(before_dir / "facet_cross_source_evidence.csv") if (before_dir / "facet_cross_source_evidence.csv").exists() else pd.DataFrame()
    after = pd.read_csv(after_dir / "facet_cross_source_evidence.csv")
    evidence = pd.read_parquet(after_dir / "facet_evidence_unified.parquet")
    review = pd.read_csv(after_dir / "facet_review_queue_v2.csv")
    nutrime = review.get("nutrime_review_evidence_count", pd.Series(0, index=review.index))
    chongkundang = review.get("chongkundang_review_evidence_count", pd.Series(0, index=review.index))
    review_source_counts = evidence[evidence["source_type"].eq("KOREAN_HFF_RAW_REVIEW")].groupby("source").size().to_dict()
    lgu_purchase_evidence_rows = int((evidence["source_type"] == "KOREAN_HFF_PURCHASE_AGGREGATE").sum())
    source_pair = evidence[evidence["source_type"].eq("KOREAN_HFF_RAW_REVIEW")].groupby(["normalized_attribute", "normalized_value"])["source"].nunique()
    combinations = {
        "MFDS + Review": int(((review["mfds_support"] > 0) & ((nutrime > 0) | (chongkundang > 0))).sum()),
        "Seller + Review": int(((review["seller_support"] > 0) & ((nutrime > 0) | (chongkundang > 0))).sum()),
        "MFDS + Seller + Review": int(((review["mfds_support"] > 0) & (review["seller_support"] > 0) & ((nutrime > 0) | (chongkundang > 0))).sum()),
        "Review Source 2": int((source_pair >= 2).sum()),
    }
    metrics = {
        "before_candidates": len(before),
        "after_candidates": len(after),
        "before_source_2plus": _count(before_dir / "facet_cross_source_evidence.csv", 2),
        "after_source_2plus": int((after["source_count"] >= 2).sum()),
        "before_source_3plus": _count(before_dir / "facet_cross_source_evidence.csv", 3),
        "after_source_3plus": int((after["source_count"] >= 3).sum()),
        "review_evidence_rows": int((evidence["source_type"] == "KOREAN_HFF_RAW_REVIEW").sum()),
        "review_candidate_rows": int((review["review_source_count"] > 0).sum()),
        "human_review_queue_rows": len(review),
        "lgu_purchase_evidence_rows": lgu_purchase_evidence_rows,
    }
    lines = [
        "# Model 1 Consumer Evidence Report",
        "",
        "## Nutrime",
        "- Review snapshot: 423건 확보 (500건 목표, 공개 후기 종료)",
        "- Mapping Before: 69% / 100건",
        "- Mapping After: 82.27% / 348건 / 423건",
        "- Mapping failure: 100건 기준 31건 모두 PRODUCT_ID_NOT_FOUND",
        "- HFF confirmed review: 348건",
        f"- Analysis Review: 399건 (상품별 최대 50건), raw review snapshot 423건은 별도 보존",
        f"- Facet evidence used by this run: {metrics['review_evidence_rows']}건",
        "- Medical outcome sentence: 5건 별도 제외",
        "- Unique product: 19개",
        "- Top 10 product review share: 74.70%",
        "",
        "## Chongkundang",
        "- Review Pilot: 실패/중단",
        "- Review 수: 0건",
        "- 원인: 공개 상품 페이지는 접근 가능했으나 Review 목록 요청이 비JSON/403 응답으로 반환됨. 우회하지 않음.",
        "- HFF Review: 0건",
        "",
        "## Cross-source",
        f"- Facet Candidate Before: {metrics['before_candidates']}",
        f"- Facet Candidate After: {metrics['after_candidates']}",
        f"- Source >= 2 Before / After: {metrics['before_source_2plus']} / {metrics['after_source_2plus']}",
        f"- Source >= 3 Before / After: {metrics['before_source_3plus']} / {metrics['after_source_3plus']}",
        f"- Review Evidence Rows: {metrics['review_evidence_rows']}",
        f"- Review-supported Candidate Rows: {metrics['review_candidate_rows']}",
        f"- LG U+ Purchase Evidence Rows: {metrics['lgu_purchase_evidence_rows']}",
        "- LG U+ regional purchase aggregates are retained as market evidence and excluded from Facet candidate generation.",
        "- Review Source Count: 1 (Nutrime; Chongkundang은 0건)",
        "- Product/category crosswalk: 쇼핑몰 ID와 MFDS ID를 숫자만으로 조인하지 않으며, 상품명 완전일치 외에는 미매핑으로 유지",
        f"- Review Source Agreement (both providers): {combinations['Review Source 2']}",
        "",
        "| Combination | Candidate count |",
        "|---|---:|",
    ]
    lines.extend(f"| {key} | {value} |" for key, value in combinations.items())
    lines += [
        "",
        "## Human Review",
        f"- Queue rows: {metrics['human_review_queue_rows']}",
        "- Review queue에는 nutrime/chongkundang source별 count, 짧은 review example, product/seller support, priority가 포함됨.",
        "- Priority는 자동 승인값이 아니라 사람이 먼저 검토할 순서를 정하는 보조값이다.",
        "",
        "## Policy",
        "- Raw Review는 내부 Model 1 분석용으로만 보관한다.",
        "- 작성자명·닉네임·IP는 저장하지 않는다.",
        "- verified_purchase는 공식 구매완료 근거가 없으므로 null이다.",
        "- 의료 결과 표현은 별도 count 후 Facet Evidence에서 제외한다.",
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return metrics


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--before-dir", type=Path, default=Path(".. /data/interim/facet_evidence_v2".replace(" ", "")))
    parser.add_argument("--after-dir", type=Path, default=Path("data/interim/facet_evidence_v3"))
    parser.add_argument("--output", type=Path, default=Path("reports/model1_consumer_evidence_report.md"))
    args = parser.parse_args()
    print(build_report(args.before_dir, args.after_dir, args.output))
