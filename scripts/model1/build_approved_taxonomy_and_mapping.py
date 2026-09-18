"""Build an AI-reviewed taxonomy draft and evidence-grounded product mapping.

The delegated review is not human gold.  This script therefore keeps the
taxonomy explicitly pending human review and never uses ``ALL`` for a product
whose facet value was not observed.  Missing product evidence is emitted as
``UNMAPPED`` so it cannot be confused with the demand-side ``ALL`` value.
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

import pandas as pd

from moongcheap_ai.data_foundation.category_v2_1 import classify_v2_1


TAXONOMY_STATUS = "DRAFT_PENDING_HUMAN_REVIEW"
APPROVAL_STATUS = "AI_APPROVED_PENDING_HUMAN"
FACET_FIELDS = {
    "product_form": "product_form",
    "functional_ingredients": "functional_ingredients",
}
OUTPUT_COLUMNS = [
    "source_product_id",
    "product_name",
    "category_key",
    "category_name",
    "facet_id",
    "facet_name",
    "value",
    "value_code",
    "source_field",
    "source_text",
    "mapping_status",
    "mapping_method",
    "taxonomy_status",
    "human_approved",
]


def _text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if bool(pd.isna(value)):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _norm(value: Any) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", _text(value)).casefold())


def _category_names(inputs: pd.DataFrame) -> dict[str, str]:
    if not {"category_key", "category_name"}.issubset(inputs.columns):
        return {}
    return {
        str(row.category_key): _text(row.category_name)
        for row in inputs[["category_key", "category_name"]]
        .drop_duplicates("category_key")
        .itertuples(index=False)
    }


def build_taxonomy(approved: pd.DataFrame, category_names: dict[str, str]) -> dict[str, Any]:
    required = {"category_key", "facet_name", "value"}
    missing = sorted(required - set(approved.columns))
    if missing:
        raise ValueError(f"approved candidates missing required columns: {', '.join(missing)}")

    data = approved.fillna("").copy()
    data["category_key"] = data["category_key"].map(_text)
    data["facet_name"] = data["facet_name"].map(_text)
    data["value"] = data["value"].map(_text)
    data = data[data["category_key"].ne("") & data["facet_name"].ne("") & data["value"].ne("")]
    data = data[data["value"].map(lambda value: _norm(value) != _norm("ALL"))]
    data = data.drop_duplicates(["category_key", "facet_name", "value"])

    categories: list[dict[str, Any]] = []
    for category_key, category_group in data.groupby("category_key", sort=True):
        facets: list[dict[str, Any]] = []
        for facet_order, facet_name in enumerate(sorted(category_group["facet_name"].unique()), 1):
            values = sorted(
                category_group.loc[category_group["facet_name"].eq(facet_name), "value"].unique(),
                key=lambda value: (_norm(value), value),
            )
            facet_values = [{"code": 0, "value": "ALL", "aliases": []}]
            facet_values.extend(
                {"code": code, "value": value, "aliases": []}
                for code, value in enumerate(values, 1)
            )
            facets.append(
                {
                    "facet_id": facet_order,
                    "name": facet_name,
                    "order": facet_order,
                    "status": APPROVAL_STATUS,
                    "values": facet_values,
                }
            )
        categories.append(
            {
                "category_id": category_key,
                "category_name": category_names.get(category_key, category_key),
                "status": TAXONOMY_STATUS,
                "approval_status": APPROVAL_STATUS,
                "human_approved": False,
                "facets": facets,
            }
        )
    return {
        "status": TAXONOMY_STATUS,
        "approval_status": APPROVAL_STATUS,
        "human_approved": False,
        "source": "DELEGATED_AI_REVIEW_OF_RULE_MODEL_HYBRID",
        "all_policy": "ALL is demand-side code 0 only; missing product evidence is UNMAPPED",
        "categories": categories,
    }


def _taxonomy_lookup(taxonomy: dict[str, Any]) -> dict[tuple[str, str, str], int]:
    lookup: dict[tuple[str, str, str], int] = {}
    for category in taxonomy.get("categories", []):
        category_key = _text(category.get("category_id"))
        for facet in category.get("facets", []):
            facet_name = _text(facet.get("name"))
            for value in facet.get("values", []):
                if _text(value.get("value")) != "ALL":
                    lookup[(category_key, facet_name, _norm(value.get("value")))] = int(value["code"])
    return lookup


def build_product_mapping(products: pd.DataFrame, taxonomy: dict[str, Any]) -> pd.DataFrame:
    names = {
        _text(category.get("category_id")): _text(category.get("category_name"))
        for category in taxonomy.get("categories", [])
    }
    category_facets = {
        _text(category.get("category_id")): sorted(
            {_text(facet.get("name")) for facet in category.get("facets", [])}
        )
        for category in taxonomy.get("categories", [])
    }
    lookup = _taxonomy_lookup(taxonomy)
    rows: list[dict[str, Any]] = []
    for _, product in products.fillna("").iterrows():
        category_id, category_name, _, _ = classify_v2_1(product)
        category_key = f"health-functional-food:{category_id.lower()}" if _text(product.get("product_type")) else "UNMAPPED"
        for facet_name in category_facets.get(category_key, []):
            source_field = FACET_FIELDS.get(facet_name, "")
            source_text = _text(product.get(source_field)) if source_field else ""
            values = []
            if source_text:
                for (key, name, normalized_value), code in lookup.items():
                    if key == category_key and name == facet_name and normalized_value in _norm(source_text):
                        values.append((normalized_value, code))
            if not values:
                rows.append(
                    {
                        "source_product_id": _text(product.get("source_product_id")),
                        "product_name": _text(product.get("name")),
                        "category_key": category_key,
                        "category_name": names.get(category_key, category_name),
                        "facet_id": next(
                            (facet.get("facet_id") for category in taxonomy.get("categories", []) if category.get("category_id") == category_key for facet in category.get("facets", []) if facet.get("name") == facet_name),
                            "",
                        ),
                        "facet_name": facet_name,
                        "value": "",
                        "value_code": "",
                        "source_field": source_field,
                        "source_text": source_text,
                        "mapping_status": "UNMAPPED",
                        "mapping_method": "NO_OBSERVED_VALUE",
                        "taxonomy_status": TAXONOMY_STATUS,
                        "human_approved": False,
                    }
                )
            else:
                for normalized_value, code in sorted(set(values)):
                    display_value = next(
                        value.get("value")
                        for category in taxonomy.get("categories", [])
                        if category.get("category_id") == category_key
                        for facet in category.get("facets", [])
                        if facet.get("name") == facet_name
                        for value in facet.get("values", [])
                        if _norm(value.get("value")) == normalized_value
                    )
                    rows.append(
                        {
                            "source_product_id": _text(product.get("source_product_id")),
                            "product_name": _text(product.get("name")),
                            "category_key": category_key,
                            "category_name": names.get(category_key, category_name),
                            "facet_id": next(
                                (facet.get("facet_id") for category in taxonomy.get("categories", []) if category.get("category_id") == category_key for facet in category.get("facets", []) if facet.get("name") == facet_name),
                                "",
                            ),
                            "facet_name": facet_name,
                            "value": display_value,
                            "value_code": code,
                            "source_field": source_field,
                            "source_text": source_text,
                            "mapping_status": "MAPPED",
                            "mapping_method": "NORMALIZED_SUBSTRING_OBSERVED",
                            "taxonomy_status": TAXONOMY_STATUS,
                            "human_approved": False,
                        }
                    )
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--approved", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--products", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    approved = pd.read_csv(args.approved, dtype=str).fillna("")
    inputs = pd.read_json(args.input, lines=True).fillna("")
    products = pd.read_csv(args.products, dtype=str).fillna("")
    taxonomy = build_taxonomy(approved, _category_names(inputs))
    mapping = build_product_mapping(products, taxonomy)
    (args.output_dir / "facet_taxonomy_v0.json").write_text(json.dumps(taxonomy, ensure_ascii=False, indent=2), encoding="utf-8")
    approved.to_csv(args.output_dir / "facet_review_queue_ai_approved.csv", index=False, encoding="utf-8-sig")
    mapping.to_csv(args.output_dir / "product_facet_mapping_ai_approved.csv", index=False, encoding="utf-8-sig")
    print(json.dumps({
        "categories": len(taxonomy["categories"]),
        "facets": sum(len(category["facets"]) for category in taxonomy["categories"]),
        "values_without_all": sum(len(facet["values"]) - 1 for category in taxonomy["categories"] for facet in category["facets"]),
        "mapping_rows": len(mapping),
        "mapped_rows": int(mapping["mapping_status"].eq("MAPPED").sum()) if not mapping.empty else 0,
        "unmapped_rows": int(mapping["mapping_status"].eq("UNMAPPED").sum()) if not mapping.empty else 0,
        "human_approved": False,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
