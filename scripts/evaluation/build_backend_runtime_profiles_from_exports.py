"""Build B runtime profiles from Backend's actual CSV exports.

The export contract is intentionally separate from the old Seed v5 contract:
``product_catalog.id`` and ``product_catalog.category_id`` are Backend IDs.
Rows without a usable Facet taxonomy are retained as ``INSUFFICIENT_EVIDENCE``
so a missing profile cannot abort the whole batch. They are not promoted as
Facet evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

PROFILE_COLUMNS = [
    "catalog_id",
    "product_name",
    "service_category_id",
    "taxonomy_version",
    "product_form",
    "functional_ingredients_json",
    "main_functionality_claim_ids_json",
    "main_functionality_claim_texts_json",
    "intake_method_text",
    "profile_status",
]

# Conservative category-name fallback for Backend categories whose facet JSON
# is still empty. This makes profile coverage complete without pretending that
# missing category evidence is resolved.
FALLBACK_CATEGORY_BY_NAME = {
    "철분": "health-functional-food:vitamin_mineral",
    "아연": "health-functional-food:vitamin_mineral",
    "엽산": "health-functional-food:vitamin_mineral",
    "마그네슘": "health-functional-food:vitamin_mineral",
    "칼슘": "health-functional-food:vitamin_mineral",
    "칼륨": "health-functional-food:vitamin_mineral",
    "크릴오일": "health-functional-food:omega_fatty_acid",
}
DEFAULT_FALLBACK_CATEGORY = "health-functional-food:other_functional"


def _json(values: list[str]) -> str:
    return json.dumps(sorted({str(value).strip() for value in values if str(value).strip()}), ensure_ascii=False)


def _facet_category(category_row: dict[str, Any]) -> str:
    raw = str(category_row.get("facet", "")).strip()
    if not raw:
        return ""
    try:
        return str(json.loads(raw).get("category_id", "")).strip()
    except json.JSONDecodeError:
        return ""


def build_profiles_from_exports(
    mapping: pd.DataFrame,
    categories: pd.DataFrame,
    product_facets: pd.DataFrame,
    taxonomy: dict[str, Any],
    source_mapping: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    required_mapping = {
        "product_catalog.id",
        "product_catalog.name",
        "product_catalog.category_id",
    }
    missing = required_mapping - set(mapping.columns)
    if missing:
        raise ValueError(f"Backend mapping missing columns: {sorted(missing)}")
    required_categories = {"id", "name", "facet"}
    missing = required_categories - set(categories.columns)
    if missing:
        raise ValueError(f"Backend category export missing columns: {sorted(missing)}")
    required_facets = {"source_product_id", "facet_name", "value", "mapping_status"}
    missing = required_facets - set(product_facets.columns)
    if missing:
        raise ValueError(f"product facet mapping missing columns: {sorted(missing)}")

    mapping = mapping.fillna("").copy()
    categories = categories.fillna("").copy()
    product_facets = product_facets.fillna("").copy()
    if source_mapping is not None:
        source_mapping = source_mapping.fillna("").copy()
        source_columns = {"catalog_id", "source_product_id"} - set(source_mapping.columns)
        if source_columns:
            raise ValueError(f"source mapping missing columns: {sorted(source_columns)}")
        source_lookup = source_mapping[["catalog_id", "source_product_id"]].drop_duplicates("catalog_id")
        mapping = mapping.merge(
            source_lookup,
            left_on="product_catalog.id",
            right_on="catalog_id",
            how="left",
            suffixes=("", "_source"),
        ).drop(columns=["catalog_id"], errors="ignore")
    if mapping["product_catalog.id"].duplicated().any():
        raise ValueError("Backend product_catalog.id must be unique")
    category_by_id = {
        str(row["id"]): row.to_dict() for _, row in categories.iterrows()
    }
    taxonomy_ids = {str(item["category_id"]) for item in taxonomy.get("categories", [])}
    version = str(taxonomy.get("version", taxonomy.get("taxonomy_version", "")))
    if not version:
        raise ValueError("taxonomy version is required")

    # The latest Backend export does not need the old Seed ID. Facet mappings
    # still use source_product_id, so retain that relationship when available.
    facet_by_source: dict[str, pd.DataFrame] = {
        str(source): group
        for source, group in product_facets.groupby("source_product_id", sort=False)
    }
    rows: list[dict[str, str]] = []
    resolution_counts: dict[str, int] = {}
    for item in mapping.to_dict("records"):
        catalog_id = str(item["product_catalog.id"]).strip()
        category_id = str(item["product_catalog.category_id"]).strip()
        category = category_by_id.get(category_id)
        if category is None:
            raise ValueError(f"mapping references missing Backend category.id: {category_id}")
        service_category = _facet_category(category)
        resolution = "CATEGORY_FACET"
        if not service_category or service_category not in taxonomy_ids:
            category_name = str(category.get("name", "")).strip()
            service_category = FALLBACK_CATEGORY_BY_NAME.get(category_name, DEFAULT_FALLBACK_CATEGORY)
            resolution = "CATEGORY_FACET_MISSING_FALLBACK"
        if service_category not in taxonomy_ids:
            raise ValueError(f"fallback category is absent from taxonomy: {service_category}")
        resolution_counts[resolution] = resolution_counts.get(resolution, 0) + 1

        source_id = str(item.get("source_product_id", "")).strip()
        facets = facet_by_source.get(source_id, pd.DataFrame())
        if not facets.empty:
            facets = facets[facets["mapping_status"].astype(str).str.upper().eq("MAPPED")]
        forms = facets.loc[facets["facet_name"].eq("product_form"), "value"].tolist() if not facets.empty else []
        ingredients = facets.loc[facets["facet_name"].eq("functional_ingredients"), "value"].tolist() if not facets.empty else []
        evidence_ready = bool(forms or ingredients) and resolution == "CATEGORY_FACET"
        rows.append({
            "catalog_id": catalog_id,
            "product_name": str(item["product_catalog.name"]),
            "service_category_id": service_category,
            "taxonomy_version": version,
            "product_form": sorted({str(value) for value in forms if str(value).strip()})[0] if forms else "",
            "functional_ingredients_json": _json(ingredients),
            "main_functionality_claim_ids_json": "[]",
            "main_functionality_claim_texts_json": "[]",
            "intake_method_text": "",
            "profile_status": "EVIDENCE_READY" if evidence_ready else "INSUFFICIENT_EVIDENCE",
        })
    profiles = pd.DataFrame(rows, columns=PROFILE_COLUMNS).sort_values("catalog_id").reset_index(drop=True)
    summary = {
        "backend_mapping_rows": int(len(mapping)),
        "profile_rows": int(len(profiles)),
        "profile_status_counts": {str(k): int(v) for k, v in profiles["profile_status"].value_counts().items()},
        "category_resolution_counts": resolution_counts,
        "taxonomy_version": version,
        "identity_contract": "catalog_id is Backend product_catalog.id; service_category_id is AI taxonomy key",
        "fallback_policy": "Missing category.facet is retained as INSUFFICIENT_EVIDENCE with a conservative taxonomy fallback; no Facet value is invented",
    }
    return profiles, summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--categories", type=Path, required=True)
    parser.add_argument("--product-facets", type=Path, required=True)
    parser.add_argument("--source-mapping", type=Path, help="Old AI mapping used only to connect source_product_id to Backend catalog ID")
    parser.add_argument("--taxonomy", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise RuntimeError(f"refusing to overwrite output directory: {args.output_dir}")
    profiles, summary = build_profiles_from_exports(
        pd.read_csv(args.mapping, dtype=str, encoding="cp949").fillna(""),
        pd.read_csv(args.categories, dtype=str, encoding="utf-8-sig").fillna(""),
        pd.read_csv(args.product_facets, dtype=str, encoding="utf-8-sig").fillna(""),
        json.loads(args.taxonomy.read_text(encoding="utf-8")),
        pd.read_csv(args.source_mapping, dtype=str, encoding="utf-8-sig").fillna("") if args.source_mapping else None,
    )
    args.output_dir.mkdir(parents=True)
    profiles_path = args.output_dir / "catalog_profiles.csv"
    taxonomy_path = args.output_dir / "taxonomy.json"
    profiles.to_csv(profiles_path, index=False, encoding="utf-8-sig")
    taxonomy_path.write_bytes(args.taxonomy.read_bytes())
    manifest = {
        **summary,
        "scope": "BACKEND_PRODUCT_CATALOG_HEALTH_PROFILES",
        "taxonomySha256": hashlib.sha256(taxonomy_path.read_bytes()).hexdigest(),
        "createdAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "profileFile": profiles_path.name,
        "taxonomyFile": taxonomy_path.name,
    }
    (args.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
