"""Create Backend-ID-aligned category and product catalog seed exports."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

CATEGORY_COLUMNS = ["id", "parent_id", "name", "depth", "facet", "created_at", "updated_at"]
PRODUCT_COLUMNS = [
    "id", "name", "category_id", "spec_summary", "list_price", "thumbnail_url",
    "description", "status", "source", "source_product_id", "catalog_seed_id",
    "source_category_path", "source_category_id", "source_status",
]


def build_exports(
    categories: pd.DataFrame,
    backend_mapping: pd.DataFrame,
    old_products: pd.DataFrame,
    old_id_mapping: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, int]]:
    if set(CATEGORY_COLUMNS) - set(categories.columns):
        raise ValueError("category export is missing required columns")
    required_mapping = {"product_catalog.id", "product_catalog.name", "product_catalog.category_id"}
    if required_mapping - set(backend_mapping.columns):
        raise ValueError("Backend catalog/category mapping is missing required columns")
    if {"catalog_seed_id", "name"} - set(old_products.columns):
        raise ValueError("old product seed must contain catalog_seed_id and name")
    if {"catalog_id", "catalog_seed_id"} - set(old_id_mapping.columns):
        raise ValueError("old ID mapping must contain catalog_id and catalog_seed_id")

    categories = categories[CATEGORY_COLUMNS].fillna("").drop_duplicates("id").copy()
    backend_mapping = backend_mapping.fillna("").drop_duplicates("product_catalog.id").copy()
    old_products = old_products.fillna("").drop_duplicates("catalog_seed_id").copy()
    old_id_mapping = old_id_mapping.fillna("").drop_duplicates("catalog_seed_id").copy()

    if set(backend_mapping["product_catalog.category_id"]) - set(categories["id"]):
        raise ValueError("Backend mapping contains category IDs absent from category export")

    products = old_products.merge(
        old_id_mapping[["catalog_id", "catalog_seed_id", "source_product_id"]],
        on="catalog_seed_id",
        how="inner",
        suffixes=("", "_mapping"),
    )
    products = products.merge(
        backend_mapping[["product_catalog.id", "product_catalog.name", "product_catalog.category_id"]],
        left_on="catalog_id",
        right_on="product_catalog.id",
        how="left",
    )
    if products["product_catalog.id"].isna().any():
        raise ValueError("old product seed contains catalog IDs absent from Backend mapping")
    mismatch = products["name"].astype(str).str.strip() != products["product_catalog.name"].astype(str).str.strip()
    if mismatch.any():
        raise ValueError(f"product name mismatch count: {int(mismatch.sum())}")

    products["id"] = products["product_catalog.id"]
    products["category_id"] = products["product_catalog.category_id"]
    if "source_product_id_mapping" in products:
        products["source_product_id"] = products["source_product_id_mapping"]
    products = products[PRODUCT_COLUMNS].sort_values("id").reset_index(drop=True)
    summary = {
        "category_rows": int(len(categories)),
        "product_rows": int(len(products)),
        "backend_mapping_rows": int(len(backend_mapping)),
        "category_ids_used_by_products": int(products["category_id"].nunique()),
    }
    return categories, products, summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--categories", type=Path, required=True)
    parser.add_argument("--backend-mapping", type=Path, required=True)
    parser.add_argument("--old-products", type=Path, required=True)
    parser.add_argument("--old-id-mapping", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise RuntimeError(f"refusing to overwrite output directory: {args.output_dir}")
    category, products, summary = build_exports(
        pd.read_csv(args.categories, dtype=str, encoding="utf-8-sig"),
        pd.read_csv(args.backend_mapping, dtype=str, encoding="cp949"),
        pd.read_csv(args.old_products, dtype=str, encoding="utf-8-sig"),
        pd.read_csv(args.old_id_mapping, dtype=str, encoding="utf-8-sig"),
    )
    args.output_dir.mkdir(parents=True)
    category.to_csv(args.output_dir / "category_seed_backend_v1.csv", index=False, encoding="utf-8-sig")
    products.to_csv(args.output_dir / "product_catalog_seed_backend_v1.csv", index=False, encoding="utf-8-sig")
    (args.output_dir / "summary.json").write_text(
        __import__("json").dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(summary)


if __name__ == "__main__":
    main()
