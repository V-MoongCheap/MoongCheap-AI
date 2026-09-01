from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from .catalog import build_catalog, resolve_identity, source_rows_to_staging
from .category import build_aihub_category_hierarchy, build_observed_kan
from .config import ensure_dirs, paths
from .audit import audit_aihub, build_category_source_mapping, product_catalog_coverage, write_today_result
from .facet import preprocess_i0030, preprocess_i2710, repeated_terms, structured_distribution, taxonomy_v0, validate_i0030
from .category_seed import CategorySeedError, build_health_category_seed
from .inspect_data import inspect
from .mfds import MFDSCollectionError, collect
from .parts.aihub import read_coco_json
from .parts.aihub.exploratory_facet import build_exploratory_facets

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
LOGGER = logging.getLogger(__name__)


def report(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def read_report(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


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
                value = json.loads(path.read_text(encoding="utf-8-sig"))
                frame = read_coco_json(path) if isinstance(value, dict) and {"images", "annotations"}.issubset(value) else pd.DataFrame(value if isinstance(value, list) else value.get("data", value.get("rows", [])))
            else: continue
            if not frame.empty: result.append((str(path), frame))
        except Exception as exc:
            LOGGER.warning("Skipping %s: %s", path, exc)
    return result


def run(root: Path, stage: str = "all") -> None:
    load_dotenv(root / ".env")
    ensure_dirs(root); p = paths(root)
    aihub_audit_summary = None
    coverage_summary = None
    conflict_count = 0
    mfds_status = None
    facet_status = None
    category_seed_status = None
    completed_mfds_services: set[str] = set()
    aihub = root / "data/raw/aihub"
    image_root = aihub / "product_image"
    if not image_root.exists() or not any(path.is_file() for path in image_root.rglob("*")):
        report(p["reports"] / "aihub_product_image_audit.json", {"status": "SKIPPED", "reason": "AI-Hub product image raw data not found", "required_directory": "data/raw/aihub/product_image"})
    if stage in {"all", "inspect", "catalog"}:
        if not aihub.exists() or not any(path.is_file() for path in aihub.rglob("*")):
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
                health_mask = staging["source_category_path"].fillna("").astype(str).str.contains(r"(?:^| > )15_", regex=True, na=False)
                health_subset = staging.loc[health_mask].copy()
                health_subset.to_parquet(out / "aihub_health_food_subset_v0.parquet", index=False)
                health_subset.to_csv(out / "aihub_health_food_subset_v0.csv", index=False, encoding="utf-8-sig")
                report(p["reports"] / "aihub_health_food_subset.json", {
                    "status": "COMPLETED",
                    "scope": "AI_HUB_HEALTH_FOOD_SUBSET",
                    "warning": "This is an AI-Hub category subset, not proof of MFDS health-functional-food registration.",
                    "raw_rows": int(len(health_subset)),
                    "unique_barcode_count": int(health_subset["barcode"].nunique()),
                    "unique_valid_barcode_count": int(health_subset.loc[health_subset["barcode_valid"], "barcode"].nunique()),
                    "unique_product_name_count": int(health_subset["product_name_normalized"].nunique()),
                    "observed_kan_codes": sorted(health_subset["kan_code"].dropna().astype(str).loc[lambda values: values.ne("")].unique().tolist()),
                })
            resolved, conflicts = resolve_identity(staging)
            aihub_audit_summary, audit_conflicts = audit_aihub(staging)
            aihub_audit_summary["raw_file_count"] = len(files)
            conflict_count = len(audit_conflicts)
            report(p["reports"] / "aihub_logistics_audit.json", aihub_audit_summary)
            audit_conflicts.to_csv(p["reports"] / "aihub_barcode_conflicts.csv", index=False, encoding="utf-8-sig")
            if not conflicts.empty: conflicts.to_csv(p["reports"] / "product_identity_conflicts.csv", index=False, encoding="utf-8-sig")
            catalog, provenance = build_catalog(resolved)
            catalog_dir = root / "data/processed/product_catalog"; catalog_dir.mkdir(parents=True, exist_ok=True)
            catalog.to_parquet(catalog_dir / "product_catalog_v1.parquet", index=False)
            catalog.to_csv(catalog_dir / "product_catalog_v1.csv", index=False, encoding="utf-8-sig")
            health_codes = set(staging.loc[staging["source_category_path"].fillna("").astype(str).str.contains(r"(?:^| > )15_", regex=True, na=False), "kan_code"].astype(str))
            catalog[catalog["kan_code"].astype(str).isin(health_codes)].to_parquet(catalog_dir / "product_catalog_health_food_subset_v0.parquet", index=False)
            provenance.to_csv(catalog_dir / "product_catalog_source.csv", index=False, encoding="utf-8-sig")
            coverage_summary = product_catalog_coverage(staging, catalog)
            report(p["reports"] / "product_catalog_coverage.json", coverage_summary)
            build_category_source_mapping(staging).to_csv(p["processed_category"] / "category_source_mapping.csv", index=False, encoding="utf-8-sig")
            build_aihub_category_hierarchy(staging, p["processed_category"] / "aihub_category_hierarchy_v0.csv")
            exploratory = build_exploratory_facets(
                staging,
                p["interim_facet"] / "aihub_repeated_terms.csv",
                p["interim_facet"] / "aihub_structured_value_distribution.csv",
                p["processed_facet"] / "aihub_facet_review_queue.csv",
                p["processed_facet"] / "aihub_exploratory_facet_taxonomy_v0.json",
            )
            report(p["reports"] / "aihub_exploratory_facet_status.json", exploratory)
            build_observed_kan(staging, p["processed_category"] / "category_master_v1.csv")
            report(p["reports"] / "pipeline_status.json", {"status": "COMPLETED", "stages": "01-07", "raw_files": len(files), "raw_product_rows": len(staging), "canonical_product_count": len(catalog)})
    if stage in {"all", "mfds", "facet"}:
        api_key = os.getenv("MFDS_API_KEY")
        if api_key:
            for service in ("I0030", "I2710"):
                try:
                    max_pages_raw = os.getenv("MFDS_MAX_PAGES", "").strip()
                    max_pages = int(max_pages_raw) if max_pages_raw else None
                    result = collect(service, api_key, p["raw_mfds"] / service, max_pages=max_pages)
                    report(p["reports"] / f"mfds_{service.lower()}_collection.json", result)
                    completed_mfds_services.add(service)
                    mfds_status = {"status": "COMPLETED", "last_service": service}
                except MFDSCollectionError as exc:
                    mfds_status = {"status": "FAILED", "service": service, "reason": str(exc)}
                    report(p["reports"] / "mfds_status.json", mfds_status)
                    report(p["reports"] / f"mfds_{service.lower()}_collection.json", {"status": "FAILED", "reason": str(exc)})
                    LOGGER.warning("MFDS %s failed; continuing to write stage reports.", service)
                    break
        else:
            mfds_status = {"status": "SKIPPED", "reason": "MFDS_API_KEY is not set"}
            report(p["reports"] / "mfds_status.json", mfds_status)
            LOGGER.warning("MFDS stages skipped: MFDS_API_KEY is not set.")
        # Reuse verified local collection reports when the API rate limit blocks
        # a harmless rerun. The raw pages and their row counts are the artifact.
        for service in ("I0030", "I2710"):
            collection = read_report(p["reports"] / f"mfds_{service.lower()}_collection.json")
            if collection and collection.get("status") != "FAILED" and collection.get("rows", 0) > 0:
                completed_mfds_services.add(service)
        if completed_mfds_services == {"I0030", "I2710"}:
            mfds_status = {"status": "COMPLETED", "source": "LOCAL_RAW_PAGES"}
            report(p["reports"] / "mfds_status.json", mfds_status)
        mfds_i0030_has_raw = any((p["raw_mfds"] / "I0030").glob("page_*.json"))
        mfds_i2710_has_raw = any((p["raw_mfds"] / "I2710").glob("page_*.json"))
        mfds_has_raw = mfds_i0030_has_raw or mfds_i2710_has_raw
        if stage in {"all", "mfds", "facet"} and mfds_has_raw:
            i0030 = preprocess_i0030(p["raw_mfds"] / "I0030", p["interim_facet"] / "i0030_products_clean.csv")
            i2710 = preprocess_i2710(p["raw_mfds"] / "I2710", p["interim_facet"] / "i2710_reference.csv")
            report(p["reports"] / "mfds_i0030_preprocessing.json", i0030); report(p["reports"] / "mfds_i2710_preprocessing.json", i2710)
            source_path = p["interim_facet"] / "i0030_products_clean.csv"
            source = pd.read_csv(source_path, dtype=str).fillna("") if source_path.exists() and source_path.stat().st_size else pd.DataFrame()
            source, duplicate_rows, quality = validate_i0030(source)
            source.to_csv(p["interim_facet"] / "i0030_products_clean_dedup.csv", index=False, encoding="utf-8-sig")
            duplicate_rows.to_csv(p["interim_facet"] / "i0030_duplicate_review.csv", index=False, encoding="utf-8-sig")
            report(p["reports"] / "mfds_i0030_quality.json", quality)
            try:
                category_seed = build_health_category_seed(source)
                category_seed_path = p["processed_category"] / "health_category_seed_v0.csv"
                category_seed_path.parent.mkdir(parents=True, exist_ok=True)
                category_seed.to_csv(category_seed_path, index=False, encoding="utf-8-sig")
                category_seed_status = {"status": "DRAFT_PENDING_HUMAN_REVIEW", "rows": len(category_seed), "output": str(category_seed_path)}
            except CategorySeedError as exc:
                category_seed_status = {"status": "PENDING_SOURCE_MAPPING", "reason": str(exc)}
            report(p["reports"] / "health_category_seed_status.json", category_seed_status)
            terms = repeated_terms(source, ["name", "main_functionality", "functional_ingredients", "other_ingredients"], 3, 0.05)
            terms.to_csv(p["interim_facet"] / "repeated_terms.csv", index=False, encoding="utf-8-sig")
            structured_distribution(source, ["product_form", "product_type", "intake_method", "storage_method", "functional_ingredients", "main_functionality"]).to_csv(p["interim_facet"] / "structured_value_distribution.csv", index=False, encoding="utf-8-sig")
            if completed_mfds_services == {"I0030", "I2710"}:
                taxonomy = taxonomy_v0("SEED", "pilot", terms)
                p["processed_facet"].mkdir(parents=True, exist_ok=True)
                (p["processed_facet"] / "facet_taxonomy_v0.json").write_text(json.dumps(taxonomy, ensure_ascii=False, indent=2), encoding="utf-8")
                facet_status = {"status": "COMPLETED", "i0030_rows": i0030["processed_rows"], "i2710_rows": i2710["processed_rows"]}
            else:
                facet_status = {"status": "PARTIAL", "reason": "Only one MFDS service has raw pages; approved taxonomy was not generated.", "i0030_rows": i0030["processed_rows"], "i2710_rows": i2710["processed_rows"]}
            report(p["reports"] / "facet_status.json", facet_status)
        elif stage in {"all", "facet"}:
            facet_status = {"status": "SKIPPED", "reason": "MFDS raw data not found"}
            report(p["reports"] / "facet_status.json", facet_status)
    report(p["reports"] / "backend_schema_recommendations.json", {"migration_applied": False, "recommendations": ["thumbnail_url nullable 또는 placeholder 정책", "product_catalog_source에 external_product_id/barcode/source 저장", "category_source_mapping에 KAN 매핑 저장"]})
    # A collection failure is more informative than a stale prior SKIP report.
    collection_report = read_report(p["reports"] / "mfds_i0030_collection.json")
    if not completed_mfds_services and collection_report and collection_report.get("status") == "FAILED":
        mfds_status = {"status": "FAILED", "reason": collection_report.get("reason", "MFDS collection failed")}
        report(p["reports"] / "mfds_status.json", mfds_status)
    else:
        mfds_status = mfds_status or read_report(p["reports"] / "mfds_status.json")
    facet_status = facet_status or read_report(p["reports"] / "facet_status.json")
    if mfds_status:
        report(p["reports"] / "mfds_status.json", mfds_status)
    if stage in {"all", "mfds", "facet"}:
        pipeline_report = read_report(p["reports"] / "pipeline_status.json")
        if pipeline_report:
            pipeline_report["mfds_status"] = mfds_status.get("status", "NOT_RUN")
            pipeline_report["facet_status"] = facet_status.get("status", "NOT_RUN")
            pipeline_report["health_category_seed_status"] = category_seed_status or read_report(p["reports"] / "health_category_seed_status.json")
            pipeline_report["status"] = (
                "COMPLETED"
                if mfds_status.get("status") == "COMPLETED" and facet_status.get("status") == "COMPLETED"
                else "COMPLETED_WITH_WARNINGS"
            )
            report(p["reports"] / "pipeline_status.json", pipeline_report)
    write_today_result(p["reports"] / "TODAY_RESULT.md", aihub_audit_summary, coverage_summary, mfds_status, facet_status, conflict_count)


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--root", type=Path, default=Path.cwd()); parser.add_argument("--stage", choices=["all", "inspect", "catalog", "mfds", "facet"], default="all")
    args = parser.parse_args(); run(args.root, args.stage)


if __name__ == "__main__": main()
