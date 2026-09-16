from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from moongcheap_ai.demand_clustering.evaluation.mfds_product_profiles import (
    build_catalog_wide_mappings,
    build_mfds_product_profile_candidates,
)
from moongcheap_ai.demand_clustering.part_a_integration import (
    file_digest, taxonomy_version, validate_profile_versions,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build MFDS evidence profiles for every mapped Part A health "
            "catalog candidate without using synthetic Demand rows"
        )
    )
    parser.add_argument("--category-mapping", type=Path, required=True)
    parser.add_argument(
        "--products",
        type=Path,
        default=Path(
            "data/interim/facet_discovery/i0030_products_clean_dedup.csv"
        ),
    )
    parser.add_argument(
        "--references",
        type=Path,
        default=Path("data/interim/facet_discovery/i2710_reference.csv"),
    )
    parser.add_argument(
        "--claims",
        type=Path,
        default=Path("data/reports/mfds_function_claim_candidates_v1.csv"),
    )
    parser.add_argument("--taxonomy", type=Path, default=Path("config/facet_taxonomy_v2_2.json"))
    parser.add_argument("--taxonomy-version", help="Optional assertion; must match the supplied taxonomy")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise RuntimeError(
            f"refusing to overwrite output directory: {args.output_dir}"
        )
    taxonomy = json.loads(args.taxonomy.read_text(encoding="utf-8"))
    version = taxonomy_version(taxonomy)
    if args.taxonomy_version is not None and args.taxonomy_version != version:
        raise ValueError("--taxonomy-version must match --taxonomy")

    category_mappings = pd.read_csv(
        args.category_mapping,
        dtype=str,
        keep_default_na=False,
    )
    catalog_mappings, mapping_summary = build_catalog_wide_mappings(
        category_mappings,
        taxonomy_version=version,
    )
    profiles, profile_summary = build_mfds_product_profile_candidates(
        catalog_mappings,
        pd.read_csv(args.products, dtype=str, keep_default_na=False),
        pd.read_csv(args.references, dtype=str, keep_default_na=False),
        pd.read_csv(args.claims, dtype=str, keep_default_na=False),
    )
    validate_profile_versions(profiles, taxonomy)
    unknown_categories = set(profiles["service_category_id"]) - {
        category["category_id"] for category in taxonomy["categories"]
    }
    if unknown_categories:
        raise ValueError(f"profile categories are missing from taxonomy: {sorted(unknown_categories)}")
    manifest = {
        **profile_summary,
        "scope": "PART_A_MAPPED_MFDS_HEALTH_CATALOG",
        "identityContract": (
            "catalog_id equals MFDS source_product_id in this evidence "
            "artifact; bind it to Backend product_catalog.id separately"
        ),
        "mappingSummary": mapping_summary,
        "taxonomyVersion": version,
        "taxonomySha256": file_digest(args.taxonomy),
        "createdAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sourcePaths": {
            "categoryMapping": str(args.category_mapping),
            "products": str(args.products),
            "references": str(args.references),
            "claims": str(args.claims),
            "taxonomy": str(args.taxonomy),
        },
        "catalogMappingFile": "catalog_mappings.csv",
        "profileFile": "catalog_profiles.csv",
    }
    args.output_dir.mkdir(parents=True)
    (args.output_dir / "taxonomy.json").write_bytes(args.taxonomy.read_bytes())
    catalog_mappings.to_csv(
        args.output_dir / "catalog_mappings.csv",
        index=False,
        encoding="utf-8-sig",
    )
    profiles.to_csv(
        args.output_dir / "catalog_profiles.csv",
        index=False,
        encoding="utf-8-sig",
    )
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()
