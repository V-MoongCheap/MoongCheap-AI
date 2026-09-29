"""Prepare evidence-preserving Model 1 input from Domeggook API details."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def join_evidence(row: pd.Series) -> str:
    fields = (
        ("상품명", "name"),
        ("카테고리", "category_path"),
        ("키워드", "keywords"),
        ("상품설명", "description_item"),
        ("상품크기", "detail_size"),
        ("제조사", "manufacturer"),
        ("상품정보제공고시", "info_duty"),
        ("모델", "model"),
    )
    return " | ".join(
        f"{label}={str(row[column]).strip()}"
        for label, column in fields
        if str(row.get(column, "")).strip()
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    source = pd.read_csv(args.input, dtype=str).fillna("")
    rows = []
    for row in source.to_dict(orient="records"):
        rows.append(
            {
                "source_product_id": row.get("source_product_id", ""),
                "source_type": "DOMEGGOOK_API_PRODUCT",
                "source_category": row.get("category_path", ""),
                "product_name": row.get("name", ""),
                "evidence_text": join_evidence(pd.Series(row)),
                "price_text": row.get("dome_price", ""),
                "quantity_text": row.get("dome_moq", ""),
                "source_url": row.get("source_url", ""),
            }
        )
    output = pd.DataFrame(rows)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output.to_csv(args.output_dir / "domeggook_api_facet_evidence_v1.csv", index=False, encoding="utf-8-sig")
    grouped = output.groupby("source_category", dropna=False).size().sort_index()
    with (args.output_dir / "facet_input_by_category_v1.jsonl").open("w", encoding="utf-8") as handle:
        for category, group in output.groupby("source_category", dropna=False, sort=True):
            handle.write(json.dumps({
                "category_key": f"domeggook:{category}",
                "category_name": category,
                "source_type": "DOMEGGOOK_API_PRODUCT",
                "products": group[["source_product_id", "product_name", "evidence_text"]].to_dict(orient="records"),
            }, ensure_ascii=False) + "\n")
    (args.output_dir / "summary.json").write_text(json.dumps({
        "rows": len(output),
        "categories": int(output["source_category"].nunique()),
        "category_counts": {str(k): int(v) for k, v in grouped.items()},
        "source_type": "DOMEGGOOK_API_PRODUCT",
        "note": "Evidence fields are preserved by label; no inferred product facets are created.",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print({"rows": len(output), "categories": int(output["source_category"].nunique())})


if __name__ == "__main__":
    main()
