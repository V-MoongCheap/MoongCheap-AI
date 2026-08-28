from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import pandas as pd

from .catalog import build_catalog, resolve_identity, source_rows_to_staging
from .category import build_observed_kan
from .config import ensure_dirs, paths
from .facet import preprocess_i0030, preprocess_i2710, repeated_terms, structured_distribution, taxonomy_v0
from .inspect_data import inspect
from .mfds import MFDSCollectionError, collect

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
LOGGER = logging.getLogger(__name__)


def report(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def read_frames(root: Path) -> list[tuple[str, pd.DataFrame]]:
    result = []
    for path in sorted(root.rglob("*")):
        if not path.is_file(): continue
        try:
            suffix = path.suffix.lower()
            if suffix == ".csv": frame = pd.read_csv(path)
            elif suffix == ".xlsx": frame = pd.read_excel(path)
            elif suffix == ".parquet": frame = pd.read_parquet(path)
            elif suffix == ".jsonl": frame = pd.read_json(path, lines=True)
            elif suffix == ".json":
                value = json.loads(path.read_text(encoding="utf-8-sig")); frame = pd.DataFrame(value if isinstance(value, list) else value.get("data", value.get("rows", [])))
            else: continue
            if not frame.empty: result.append((str(path), frame))
        except Exception as exc:
            LOGGER.warning("Skipping %s: %s", path, exc)
    return result


def run(root: Path, stage: str = "all") -> None:
    ensure_dirs(root); p = paths(root)
    aihub = root / "data/raw/aihub"
    if stage in {"all", "inspect", "catalog"}:
        if not aihub.exists() or not any(aihub.rglob("*")):
            report(p["reports"] / "pipeline_status.json", {"status": "SKIPPED", "stages": "01-07", "reason": "AI-Hub raw data not found", "required_directories": ["data/raw/aihub/logistics_product", "data/raw/aihub/product_image"]})
            LOGGER.warning("AI-Hub raw data not found; catalog stages skipped.")
        else:
            files, samples = inspect(aihub)
            report(p["reports"] / "aihub_inspection.json", {"files": files, "samples": samples})
            pd.DataFrame(files).to_csv(p["reports"] / "aihub_file_inventory.csv", index=False, encoding="utf-8-sig")
            source_frames = [source_rows_to_staging(frame, "AI_HUB", path) for path, frame in read_frames(aihub)]
            staging = pd.concat(source_frames, ignore_index=True) if source_frames else pd.DataFrame()
            out = root / "data/interim/products"; out.mkdir(parents=True, exist_ok=True)
            if not staging.empty:
                staging.to_parquet(out / "product_staging.parquet", index=False)
                staging.to_csv(out / "product_staging_preview.csv", index=False, encoding="utf-8-sig")
            resolved, conflicts = resolve_identity(staging)
            if not conflicts.empty: conflicts.to_csv(p["reports"] / "product_identity_conflicts.csv", index=False, encoding="utf-8-sig")
            catalog, provenance = build_catalog(resolved)
            catalog_dir = root / "data/processed/product_catalog"; catalog_dir.mkdir(parents=True, exist_ok=True)
            catalog.to_parquet(catalog_dir / "product_catalog_v1.parquet", index=False)
            catalog.to_csv(catalog_dir / "product_catalog_v1.csv", index=False, encoding="utf-8-sig")
            provenance.to_csv(catalog_dir / "product_catalog_source.csv", index=False, encoding="utf-8-sig")
            report(p["reports"] / "product_catalog_coverage.json", {"raw_product_rows": len(staging), "unique_barcode_count": int(staging["barcode"].replace("", pd.NA).nunique()) if not staging.empty else 0, "canonical_product_count": len(catalog), "source_counts": staging["source"].value_counts().to_dict() if not staging.empty else {}})
            build_observed_kan(staging, p["processed_category"] / "category_master_v1.csv")
    if stage in {"all", "mfds", "facet"}:
        api_key = __import__("os").getenv("MFDS_API_KEY")
        if api_key:
            for service in ("I0030", "I2710"):
                try:
                    result = collect(service, api_key, p["raw_mfds"] / service, max_pages=__import__("os").getenv("MFDS_MAX_PAGES") and int(__import__("os").getenv("MFDS_MAX_PAGES")))
                    report(p["reports"] / f"mfds_{service.lower()}_collection.json", result)
                except MFDSCollectionError as exc:
                    report(p["reports"] / f"mfds_{service.lower()}_collection.json", {"status": "FAILED", "reason": str(exc)})
                    raise
        else:
            report(p["reports"] / "mfds_status.json", {"status": "SKIPPED", "reason": "MFDS_API_KEY is not set"})
            LOGGER.warning("MFDS stages skipped: MFDS_API_KEY is not set.")
        mfds_has_raw = any(any((p["raw_mfds"] / service).glob("page_*.json")) for service in ("I0030", "I2710"))
        if stage in {"all", "facet"} and mfds_has_raw:
            i0030 = preprocess_i0030(p["raw_mfds"] / "I0030", p["interim_facet"] / "i0030_products_clean.csv")
            i2710 = preprocess_i2710(p["raw_mfds"] / "I2710", p["interim_facet"] / "i2710_reference.csv")
            report(p["reports"] / "mfds_i0030_preprocessing.json", i0030); report(p["reports"] / "mfds_i2710_preprocessing.json", i2710)
            source_path = p["interim_facet"] / "i0030_products_clean.csv"
            source = pd.read_csv(source_path, dtype=str).fillna("") if source_path.exists() and source_path.stat().st_size else pd.DataFrame()
            terms = repeated_terms(source, ["name", "main_functionality", "functional_ingredients", "other_ingredients"], 3, 0.05)
            terms.to_csv(p["interim_facet"] / "repeated_terms.csv", index=False, encoding="utf-8-sig")
            structured_distribution(source, ["product_form", "product_type", "intake_method", "storage_method", "functional_ingredients", "main_functionality"]).to_csv(p["interim_facet"] / "structured_value_distribution.csv", index=False, encoding="utf-8-sig")
            taxonomy = taxonomy_v0("SEED", "pilot", terms)
            p["processed_facet"].mkdir(parents=True, exist_ok=True)
            (p["processed_facet"] / "facet_taxonomy_v0.json").write_text(json.dumps(taxonomy, ensure_ascii=False, indent=2), encoding="utf-8")
        elif stage in {"all", "facet"}:
            report(p["reports"] / "facet_status.json", {"status": "SKIPPED", "reason": "MFDS raw data not found"})
    report(p["reports"] / "backend_schema_recommendations.json", {"migration_applied": False, "recommendations": ["thumbnail_url nullable 또는 placeholder 정책", "product_catalog_source에 external_product_id/barcode/source 저장", "category_source_mapping에 KAN 매핑 저장"]})


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--root", type=Path, default=Path.cwd()); parser.add_argument("--stage", choices=["all", "inspect", "catalog", "mfds", "facet"], default="all")
    args = parser.parse_args(); run(args.root, args.stage)


if __name__ == "__main__": main()
