"""Map a Backend product_catalog export to the AI canonical catalog.

The Backend export is authoritative for ``product_catalog.id``.  Category IDs
are intentionally not inferred: this export does not contain ``category_id``.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pandas as pd


BACKEND_COLUMNS = {"id", "name", "spec_summary", "list_price", "thumbnail_url", "description", "status", "created_at", "updated_at"}
SEED_COLUMNS = {"catalog_seed_id", "source_product_id", "name", "category_id", "source_category_id"}


def _read(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False).fillna("")


def _normal_name(value: object) -> str:
    # Keep case significant. Case-folding can collapse distinct Backend rows
    # such as product names ending in ``KS`` and ``ks``.
    return re.sub(r"\s+", " ", str(value or "").strip())


def build_mapping(backend: pd.DataFrame, seed: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object]]:
    missing_backend = BACKEND_COLUMNS - set(backend.columns)
    missing_seed = SEED_COLUMNS - set(seed.columns)
    if missing_backend:
        raise ValueError(f"Backend export is missing columns: {sorted(missing_backend)}")
    if missing_seed:
        raise ValueError(f"canonical seed is missing columns: {sorted(missing_seed)}")
    if backend["id"].duplicated().any():
        raise ValueError("Backend export contains duplicate product_catalog.id values")
    if backend["name"].map(_normal_name).duplicated().any():
        raise ValueError("Backend export contains duplicate names; refusing name-based mapping")
    if seed["name"].map(_normal_name).duplicated().any():
        raise ValueError("canonical seed contains duplicate names; refusing name-based mapping")

    backend = backend.rename(
        columns={
            "name": "name_backend",
            "status": "status_backend",
            "created_at": "created_at_backend",
            "updated_at": "updated_at_backend",
        }
    ).copy()
    seed = seed.rename(columns={"name": "name_seed"}).copy()
    backend["name_key"] = backend["name_backend"].map(_normal_name)
    seed["name_key"] = seed["name_seed"].map(_normal_name)
    mapping = backend.merge(seed, on="name_key", how="outer", indicator=True)
    unmatched = mapping.loc[mapping["_merge"] != "both"]
    if not unmatched.empty:
        sample = unmatched[["name_backend", "name_seed", "_merge"]].head(10).to_dict(orient="records")
        raise ValueError(f"Backend/seed catalog mismatch: {len(unmatched)} rows; sample={sample}")

    result = mapping.rename(
        columns={
            "id": "catalog_id",
            "name_backend": "backend_name",
            "name_seed": "canonical_name",
            "catalog_seed_id": "catalog_seed_id",
            "source_product_id": "source_product_id",
            "category_id": "category_key",
            "source_category_id": "source_category_id",
        }
    )[[
        "catalog_id", "backend_name", "canonical_name", "catalog_seed_id",
        "source_product_id", "category_key", "source_category_id",
        "status_backend", "created_at_backend", "updated_at_backend",
    ]].copy()
    result["match_method"] = "EXACT_NORMALIZED_WHITESPACE_NAME"
    result["mapping_status"] = "CATALOG_ID_MAPPED_CATEGORY_ID_NOT_IN_EXPORT"
    result = result.sort_values("catalog_id", key=lambda col: col.astype(int)).reset_index(drop=True)
    report = {
        "backend_rows": len(backend),
        "canonical_seed_rows": len(seed),
        "mapped_rows": len(result),
        "unmatched_rows": 0,
        "catalog_id_min": str(result["catalog_id"].iloc[0]) if len(result) else "",
        "catalog_id_max": str(result["catalog_id"].iloc[-1]) if len(result) else "",
        "category_id_available": False,
        "category_id_policy": "Do not infer Backend category.id from category_key or numeric ranges.",
        "mapping_method": "Exact normalized product name against canonical seed; source_product_id retained for provenance.",
    }
    return result, report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend-export", type=Path, required=True)
    parser.add_argument("--canonical-seed", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    backend = _read(args.backend_export)
    seed = _read(args.canonical_seed)
    result, report = build_mapping(backend, seed)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output_dir / "backend_catalog_id_mapping_v1.csv", index=False, encoding="utf-8-sig")
    (args.output_dir / "backend_catalog_id_mapping_v1.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
