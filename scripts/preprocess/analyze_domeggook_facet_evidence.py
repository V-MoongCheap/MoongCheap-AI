"""Build category-level repeated-term evidence for the public API corpus."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


TEXT_FIELDS = [
    "name",
    "keywords",
    "description_item",
]


def terms(value: str) -> set[str]:
    import re

    text = re.sub(r"https?://\S+|www\.\S+", " ", str(value))
    text = re.sub(r"<[^>]+>|&[a-zA-Z0-9#]+;", " ", text)
    blocked = {"http", "https", "www", "img", "src", "center", "div", "style"}
    return {
        token.lower()
        for token in re.findall(r"[가-힣A-Za-z0-9]{2,}", text)
        if token.lower() not in blocked
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--min-category-products", type=int, default=10)
    parser.add_argument("--min-documents", type=int, default=3)
    parser.add_argument("--min-ratio", type=float, default=0.05)
    args = parser.parse_args()
    frame = pd.read_csv(args.input, dtype=str).fillna("")
    output: list[dict[str, object]] = []
    distributions: list[dict[str, object]] = []
    eligible: dict[str, int] = {}
    for category, group in frame.groupby("category_path", sort=True):
        if len(group) < args.min_category_products:
            continue
        eligible[str(category)] = len(group)
        seen: dict[str, set[int]] = {}
        fields: dict[str, set[str]] = {}
        for index, row in group.iterrows():
            row_terms: set[str] = set()
            for field in TEXT_FIELDS:
                for term in terms(row.get(field, "")):
                    row_terms.add(term)
                    fields.setdefault(term, set()).add(field)
            for term in row_terms:
                seen.setdefault(term, set()).add(int(index))
        for term, indexes in seen.items():
            count = len(indexes)
            ratio = count / len(group)
            if count >= args.min_documents and ratio >= args.min_ratio:
                output.append({
                    "category_name": category,
                    "category_product_count": len(group),
                    "term": term,
                    "document_count": count,
                    "document_ratio": round(ratio, 6),
                    "source_fields": "|".join(sorted(fields[term])),
                })
        for field in ("detail_size", "manufacturer", "model"):
            values = group[field].astype(str).str.strip()
            for value, count in values[values != ""].value_counts().items():
                distributions.append({
                    "category_name": category,
                    "source_field": field,
                    "normalized_value": value.lower(),
                    "count": int(count),
                    "document_ratio": round(float(count / len(group)), 6),
                })
    args.output_dir.mkdir(parents=True, exist_ok=True)
    repeated = pd.DataFrame(output).sort_values(["category_name", "document_count", "term"], ascending=[True, False, True]) if output else pd.DataFrame()
    structured = pd.DataFrame(distributions).sort_values(["category_name", "source_field", "count"], ascending=[True, True, False]) if distributions else pd.DataFrame()
    repeated.to_csv(args.output_dir / "repeated_terms_v1.csv", index=False, encoding="utf-8-sig")
    structured.to_csv(args.output_dir / "structured_value_distribution_v1.csv", index=False, encoding="utf-8-sig")
    (args.output_dir / "summary.json").write_text(json.dumps({
        "input_rows": len(frame),
        "all_category_count": int(frame["category_path"].nunique()),
        "eligible_category_count": len(eligible),
        "eligible_category_products": eligible,
        "repeated_term_rows": len(repeated),
        "structured_distribution_rows": len(structured),
        "min_category_products": args.min_category_products,
        "min_documents": args.min_documents,
        "min_ratio": args.min_ratio,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"eligible_categories": len(eligible), "repeated_terms": len(repeated), "structured_values": len(structured)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
