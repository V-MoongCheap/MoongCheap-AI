"""Build reviewable health-category, catalog, and facet candidates from MFDS facts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


FACET_FIELDS = {
    "product_form": "제품 형태",
    "functional_ingredients": "기능성 원료",
    "intake_method": "섭취 방법",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def build_health_artifacts(frame: pd.DataFrame, output_dir: Path) -> dict[str, Any]:
    """Write candidate artifacts without assigning production IDs or taxonomy codes."""
    output_dir.mkdir(parents=True, exist_ok=True)
    data = frame.fillna("").copy()
    data["product_type"] = data["product_type"].map(_text)
    categorized = data[data["product_type"] != ""].copy()

    category_rows = []
    for category, group in categorized.groupby("product_type", sort=True):
        first = group.iloc[0]
        category_rows.append({
            "source_category": category,
            "source_category_code": "",
            "product_count": len(group),
            "example_source_product_id": _text(first["source_product_id"]),
            "example_product_name": _text(first["name"]),
            "source_field": "PRDLST_CDNM",
            "review_status": "NEEDS_REVIEW",
            "review_note": "MFDS observed product classification; not a final service category",
        })
    category_analysis = pd.DataFrame(category_rows)
    category_analysis.to_csv(output_dir / "category_source_analysis.csv", index=False, encoding="utf-8-sig")

    category_seed = pd.DataFrame([
        {"category_id": "", "category_key": "health-functional-food", "parent_id": "", "name": "건강기능식품", "depth": 1, "source": "MFDS_SCOPE", "status": "NEEDS_REVIEW"},
        *({"category_id": "", "category_key": f"health-functional-food:{name}", "parent_id": "", "name": name, "depth": 2, "source": "MFDS_OBSERVED", "status": "NEEDS_REVIEW"} for name in category_analysis["source_category"]),
    ])
    category_seed.to_csv(output_dir / "category_v0.csv", index=False, encoding="utf-8-sig")

    mapping = data[["source_product_id", "name", "product_type"]].rename(columns={"name": "product_name", "product_type": "source_category"})
    mapping["source_category_code"] = ""
    mapping["suggested_category_id"] = ""
    mapping["suggested_category_name"] = mapping["source_category"]
    mapping["mapping_reason"] = "MFDS PRDLST_CDNM observed value"
    mapping["confidence"] = 1.0
    mapping["review_status"] = mapping["source_category"].map(lambda value: "NEEDS_REVIEW" if value else "BLOCKED_MISSING_SOURCE_CATEGORY")
    mapping["review_note"] = mapping["source_category"].map(lambda value: "Service category ID requires human approval" if value else "MFDS source category is missing")
    mapping.to_csv(output_dir / "product_category_mapping_review.csv", index=False, encoding="utf-8-sig")

    catalog_rows = []
    source_mapping_rows = []
    for index, row in data.reset_index(drop=True).iterrows():
        catalog_id = f"catalog-mfds-candidate-{index + 1:06d}"
        catalog_rows.append({
            "catalog_id": catalog_id,
            "source_product_id": _text(row["source_product_id"]),
            "name": _text(row["name"]),
            "category_id": "",
            "source_category": _text(row["product_type"]),
            "product_form": _text(row["product_form"]),
            "functional_ingredients": _text(row["functional_ingredients"]),
            "manufacturer": _text(row["manufacturer"]),
            "catalog_status": "NEEDS_REVIEW",
        })
        source_mapping_rows.append({"catalog_id": catalog_id, "source_id": "MFDS", "source_product_id": _text(row["source_product_id"])})
    pd.DataFrame(catalog_rows).to_csv(output_dir / "product_catalog_v0.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(source_mapping_rows).to_csv(output_dir / "catalog_source_mapping.csv", index=False, encoding="utf-8-sig")

    review_rows = []
    taxonomy_categories: list[dict[str, Any]] = []
    for category, group in categorized.groupby("product_type", sort=True):
        facets = []
        for facet_id, (field, definition) in enumerate(FACET_FIELDS.items(), 1):
            values = group[field].map(_text)
            counts = values[values != ""].value_counts()
            if counts.empty:
                continue
            facet_values = []
            for value, support in counts.head(10).items():
                example = group.loc[values == value].iloc[0]
                review_rows.append({
                    "category": category,
                    "facet_id": facet_id,
                    "facet_name": field,
                    "definition": definition,
                    "candidate_value": value,
                    "source_field": field,
                    "source_product_id": _text(example["source_product_id"]),
                    "source_example": _text(example[field]),
                    "support_count": int(support),
                    "review_status": "NEEDS_REVIEW",
                    "review_note": "Candidate only; do not treat as consumer-intent ground truth",
                })
                facet_values.append({"value": value, "support_count": int(support), "aliases": [], "review_status": "NEEDS_REVIEW"})
            facets.append({"facet_id": facet_id, "name": field, "definition": definition, "values": facet_values, "review_status": "NEEDS_REVIEW"})
        taxonomy_categories.append({"category_key": f"health-functional-food:{category}", "source_category": category, "facets": facets, "status": "DRAFT_PENDING_HUMAN_REVIEW"})
    pd.DataFrame(review_rows).to_csv(output_dir / "taxonomy_review_v0.csv", index=False, encoding="utf-8-sig")
    (output_dir / "taxonomy_candidate_v0.json").write_text(json.dumps({"status": "DRAFT_PENDING_HUMAN_REVIEW", "categories": taxonomy_categories}, ensure_ascii=False, indent=2), encoding="utf-8")

    return {"product_rows": len(data), "source_category_count": len(category_analysis), "facet_candidate_rows": len(review_rows), "status": "DRAFT_PENDING_HUMAN_REVIEW"}
