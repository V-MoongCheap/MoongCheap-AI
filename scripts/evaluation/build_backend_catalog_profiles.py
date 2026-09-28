"""Build B runtime catalog profiles with Backend catalog IDs.

This artifact intentionally uses the Backend ``product_catalog.id`` while
retaining the AI service taxonomy key as ``service_category_id``. It does not
guess or require the not-yet-published Backend ``category.id`` relation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


REQUIRED_MAPPING = {"catalog_id", "catalog_seed_id", "source_category_id"}
REQUIRED_FACETS = {"catalog_id", "facet_name", "value", "mapping_status"}
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


def _json(values: list[str]) -> str:
    return json.dumps(sorted(set(value for value in values if value)), ensure_ascii=False)


def build_profiles(
    backend_mapping: pd.DataFrame,
    product_facets: pd.DataFrame,
    backend_catalog: pd.DataFrame,
    taxonomy: dict[str, Any],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    missing = REQUIRED_MAPPING - set(backend_mapping.columns)
    if missing:
        raise ValueError(f"backend mapping missing columns: {sorted(missing)}")
    missing = REQUIRED_FACETS - set(product_facets.columns)
    if missing:
        raise ValueError(f"product facet mapping missing columns: {sorted(missing)}")
    if "id" not in backend_catalog.columns or "name" not in backend_catalog.columns:
        raise ValueError("backend catalog export requires id and name columns")
    if backend_catalog["id"].duplicated().any():
        raise ValueError("Backend product_catalog IDs must be unique")
    if backend_mapping["catalog_id"].duplicated().any():
        raise ValueError("backend catalog IDs must be unique")

    taxonomy_ids = {str(item["category_id"]) for item in taxonomy.get("categories", [])}
    names = dict(zip(backend_catalog["id"].astype(str), backend_catalog["name"].astype(str), strict=True))
    missing_backend_ids = sorted(set(backend_mapping["catalog_id"].astype(str)) - set(names))
    if missing_backend_ids:
        raise ValueError(
            "mapping contains catalog IDs absent from Backend export: "
            + ", ".join(missing_backend_ids[:20])
        )
    rows: list[dict[str, str]] = []
    excluded = 0
    for item in backend_mapping.fillna("").to_dict("records"):
        catalog_id = str(item["catalog_id"]).strip()
        service_category = str(item["source_category_id"]).strip()
        if not service_category:
            excluded += 1
            continue
        if service_category not in taxonomy_ids:
            raise ValueError(f"mapping category is missing from taxonomy: {service_category}")
        seed_id = str(item["catalog_seed_id"]).strip()
        facet_rows = product_facets[
            product_facets["catalog_id"].astype(str).eq(seed_id)
            & product_facets["mapping_status"].astype(str).str.upper().eq("MAPPED")
        ]
        forms = facet_rows.loc[facet_rows["facet_name"].eq("product_form"), "value"].astype(str).tolist()
        ingredients = facet_rows.loc[facet_rows["facet_name"].eq("functional_ingredients"), "value"].astype(str).tolist()
        status = "EVIDENCE_READY" if forms or ingredients else "INSUFFICIENT_EVIDENCE"
        rows.append({
            "catalog_id": catalog_id,
            "product_name": names.get(catalog_id, str(item.get("backend_name", ""))),
            "service_category_id": service_category,
            "taxonomy_version": str(taxonomy.get("version", taxonomy.get("taxonomy_version", ""))),
            "product_form": sorted(set(forms))[0] if forms else "",
            "functional_ingredients_json": _json(ingredients),
            "main_functionality_claim_ids_json": "[]",
            "main_functionality_claim_texts_json": "[]",
            "intake_method_text": "",
            "profile_status": status,
        })
    profiles = pd.DataFrame(rows, columns=PROFILE_COLUMNS).sort_values("catalog_id").reset_index(drop=True)
    summary = {
        "backend_catalog_rows": int(len(backend_catalog)),
        "profile_rows": int(len(profiles)),
        "excluded_without_service_category": excluded,
        "profile_status_counts": {str(k): int(v) for k, v in profiles["profile_status"].value_counts().items()},
        "taxonomy_version": str(taxonomy.get("version", taxonomy.get("taxonomy_version", ""))),
        "identity_contract": "catalog_id is Backend product_catalog.id; service_category_id is AI taxonomy key",
        "backend_category_id_required": False,
    }
    return profiles, summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend-mapping", type=Path, required=True)
    parser.add_argument("--product-facets", type=Path, required=True)
    parser.add_argument("--backend-catalog", type=Path, required=True)
    parser.add_argument("--taxonomy", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise RuntimeError(f"refusing to overwrite output directory: {args.output_dir}")
    profiles, summary = build_profiles(
        pd.read_csv(args.backend_mapping, dtype=str).fillna(""),
        pd.read_csv(args.product_facets, dtype=str).fillna(""),
        pd.read_csv(args.backend_catalog, dtype=str).fillna(""),
        json.loads(args.taxonomy.read_text(encoding="utf-8")),
    )
    args.output_dir.mkdir(parents=True)
    profiles_path = args.output_dir / "catalog_profiles.csv"
    taxonomy_path = args.output_dir / "taxonomy.json"
    manifest_path = args.output_dir / "manifest.json"
    profiles.to_csv(profiles_path, index=False, encoding="utf-8-sig")
    taxonomy_bytes = args.taxonomy.read_bytes()
    taxonomy_path.write_bytes(taxonomy_bytes)
    manifest = {
        **summary,
        "scope": "BACKEND_PRODUCT_CATALOG_HEALTH_PROFILES",
        "identityContract": (
            "catalog_id equals Backend product_catalog.id; "
            "service_category_id is the AI taxonomy key; Backend category.id is not required"
        ),
        "taxonomyVersion": summary["taxonomy_version"],
        "taxonomySha256": hashlib.sha256(taxonomy_bytes).hexdigest(),
        "createdAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "profileFile": profiles_path.name,
        "taxonomyFile": taxonomy_path.name,
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()
