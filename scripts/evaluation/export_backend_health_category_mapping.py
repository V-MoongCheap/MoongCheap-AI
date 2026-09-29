"""Export Backend-ready health catalog/category mapping files.

The export uses Backend ``product_catalog.id`` from the catalog crosswalk and
stable AI/seed category keys.  Backend-generated ``category.id`` is deliberately
left empty because the category table is currently empty and its IDs do not
exist yet.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def export_mapping(mapping_path: Path, category_path: Path, output_dir: Path) -> dict[str, int]:
    mapping = pd.read_csv(mapping_path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    categories = pd.read_csv(category_path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    required_mapping = {"catalog_id", "backend_name", "source_product_id", "category_key", "source_category_id"}
    required_categories = {"category_key", "parent_key", "name", "depth", "facet", "source_category_path"}
    missing_mapping = required_mapping - set(mapping.columns)
    missing_categories = required_categories - set(categories.columns)
    if missing_mapping or missing_categories:
        raise ValueError(f"missing mapping={sorted(missing_mapping)}, categories={sorted(missing_categories)}")

    # The source_category_id is the AI taxonomy mapping status, not the
    # product's health/non-health classification.  A blank value can still be
    # a health-category product whose AI taxonomy mapping is unresolved.
    health = mapping[mapping["category_key"].str.contains("식품/건강식품", regex=False)].copy()
    health_keys = set(health["category_key"])

    # Include ancestors so the Backend category hierarchy remains insertable.
    selected_keys: set[str] = set(health_keys)
    by_key = categories.set_index("category_key", drop=False)
    pending = list(health_keys)
    while pending:
        key = pending.pop()
        parent = str(by_key.at[key, "parent_key"]).strip() if key in by_key.index else ""
        if parent and parent not in selected_keys:
            selected_keys.add(parent)
            pending.append(parent)
    selected_categories = categories[categories["category_key"].isin(selected_keys)].copy()
    selected_categories = selected_categories.sort_values(["depth", "source_category_path", "category_key"])
    category_export = selected_categories.reindex(
        columns=["category_key", "parent_key", "name", "depth", "source_category_path", "facet", "health_taxonomy_category_id", "source"],
        fill_value="",
    ).copy()
    category_export.insert(0, "backend_category_id", "")
    category_export.insert(1, "scope", "HEALTH_FUNCTIONAL_FOOD")

    catalog_export = health.reindex(
        columns=["catalog_id", "backend_name", "source_product_id", "category_key", "source_category_id", "status_backend", "match_method"],
        fill_value="",
    ).rename(columns={"catalog_id": "product_catalog_id", "backend_name": "product_name"})
    category_names = selected_categories.set_index("category_key")["name"].to_dict()
    catalog_export.insert(4, "category_name", catalog_export["category_key"].map(category_names).fillna(""))
    catalog_export.insert(5, "backend_category_id", "")
    catalog_export.insert(6, "scope", "HEALTH_FUNCTIONAL_FOOD")
    catalog_export.insert(7, "mapping_status", "PENDING_BACKEND_CATEGORY_INSERT")
    catalog_export.insert(
        8,
        "ai_service_category_status",
        catalog_export["source_category_id"].map(
            lambda value: "MAPPED" if str(value).strip() else "UNRESOLVED"
        ),
    )
    catalog_export.insert(
        9,
        "mapping_reason",
        catalog_export["source_category_id"].map(
            lambda value: (
                "Resolve category_key to generated category.id after Backend category INSERT"
                if str(value).strip()
                else "Backend category_key is known; AI service taxonomy mapping remains unresolved"
            )
        ),
    )
    catalog_export = catalog_export.sort_values(["category_key", "product_catalog_id"])

    output_dir.mkdir(parents=True, exist_ok=True)
    category_out = output_dir / "backend_health_category_seed_v1.csv"
    catalog_out = output_dir / "backend_health_catalog_category_mapping_v1.csv"
    category_export.to_csv(category_out, index=False, encoding="utf-8-sig")
    catalog_export.to_csv(catalog_out, index=False, encoding="utf-8-sig")
    return {
        "backend_products_total": int(len(mapping)),
        "health_products": int(len(catalog_export)),
        "non_health_products_excluded": int(len(mapping) - len(catalog_export)),
        "health_category_unresolved": int(catalog_export["ai_service_category_status"].eq("UNRESOLVED").sum()),
        "health_category_keys": int(len(health_keys)),
        "category_rows_with_ancestors": int(len(category_export)),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--categories", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(export_mapping(args.mapping, args.categories, args.output_dir))


if __name__ == "__main__":
    main()
