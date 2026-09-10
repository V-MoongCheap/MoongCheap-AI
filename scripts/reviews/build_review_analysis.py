from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import pandas as pd

from moongcheap_ai.data_foundation.facet_evidence import build_review_evidence


def load_rows(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def build_analysis(input_path: Path, evidence_dir: Path, report_path: Path) -> dict[str, object]:
    rows = load_rows(input_path)
    evidence, stats = build_review_evidence(input_path, "nutrime")
    milestones = []
    for limit in (100, 200, 300, 400, 500):
        subset = rows[:limit]
        temp = input_path.with_name(f"._review_saturation_{limit}.jsonl")
        temp.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in subset) + "\n", encoding="utf-8")
        subset_evidence, _ = build_review_evidence(temp, "nutrime")
        temp.unlink(missing_ok=True)
        keys = set(zip(subset_evidence["normalized_attribute"], subset_evidence["normalized_value"])) if not subset_evidence.empty else set()
        previous = milestones[-1]["cumulative_unique_facet_candidates"] if milestones else 0
        milestones.append({"reviews": min(limit, len(rows)), "cumulative_unique_facet_candidates": len(keys), "new_facet_candidates": max(0, len(keys) - previous)})
        if limit >= len(rows):
            break
    mapped = [row for row in rows if str(row.get("source_product_id") or "")]
    product_counts = Counter(str(row.get("source_product_id") or "") for row in mapped)
    top_products = [{"source_product_id": key, "review_count": count, "share": round(count / len(rows), 4)} for key, count in product_counts.most_common(10)]
    report = {
        "total_review_count": len(rows),
        "unique_review_count": len({str(row.get("source_review_id")) for row in rows}),
        "usable_review_text_count": sum(bool(str(row.get("review_text") or "").strip()) for row in rows),
        "duplicate_rate": 1 - len({str(row.get("source_review_id")) for row in rows}) / len(rows) if rows else 0,
        "product_mapping_rate": len(mapped) / len(rows) if rows else 0,
        "hff_confirmed_review_count": len(mapped),
        "rating_coverage": sum(row.get("rating") is not None for row in rows) / len(rows) if rows else 0,
        "date_coverage": sum(bool(str(row.get("review_date") or "").strip()) for row in rows) / len(rows) if rows else 0,
        "unique_product_count": len(product_counts),
        "top_10_product_review_share": sum(item["review_count"] for item in top_products) / len(rows) if rows else 0,
        "medical_outcome_sentence_count": stats["medical_outcome_sentence_count"],
        "facet_expression_candidate_count": stats["facet_expression_candidate_count"],
        "top_products": top_products,
        "saturation": milestones,
    }
    evidence_dir.mkdir(parents=True, exist_ok=True)
    evidence.to_csv(evidence_dir / "nutrime_review_evidence_preview.csv", index=False, encoding="utf-8-sig")
    (evidence_dir / "nutrime_review_analysis.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# Nutrime Review Facet Saturation",
        "",
        f"- Review count: {report['total_review_count']}",
        f"- Unique review count: {report['unique_review_count']}",
        f"- Usable review text: {report['usable_review_text_count']}",
        f"- Product mapping rate: {report['product_mapping_rate']:.2%}",
        f"- HFF confirmed review count: {report['hff_confirmed_review_count']}",
        f"- Rating coverage: {report['rating_coverage']:.2%}",
        f"- Date coverage: {report['date_coverage']:.2%}",
        f"- Unique product count: {report['unique_product_count']}",
        f"- Top 10 product review share: {report['top_10_product_review_share']:.2%}",
        f"- Medical outcome sentence count: {report['medical_outcome_sentence_count']}",
        f"- Facet expression candidate count: {report['facet_expression_candidate_count']}",
        "",
        "## Saturation",
        "| reviews | cumulative unique facet candidates | new facet candidates |",
        "|---:|---:|---:|",
    ]
    lines.extend(f"| {item['reviews']} | {item['cumulative_unique_facet_candidates']} | {item['new_facet_candidates']} |" for item in milestones)
    lines += ["", "## Top Product Concentration", "| source_product_id | review_count | share |", "|---|---:|---:|"]
    lines.extend(f"| {item['source_product_id']} | {item['review_count']} | {item['share']:.2%} |" for item in top_products)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("data/raw/reviews/nutrime/nutrime_reviews_500_20260909.jsonl"))
    parser.add_argument("--evidence-dir", type=Path, default=Path("data/processed/reviews/nutrime"))
    parser.add_argument("--report", type=Path, default=Path("reports/review_facet_saturation.md"))
    args = parser.parse_args()
    print(json.dumps(build_analysis(args.input, args.evidence_dir, args.report), ensure_ascii=False))
