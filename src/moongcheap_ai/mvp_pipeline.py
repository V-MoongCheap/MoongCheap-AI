"""Operational CSV MVP entry point for the V2.2 A -> B pipeline.

The production adapters remain available in ``data_foundation.runtime_job``
and ``demand_clustering.runtime_job``.  This entry point provides a repeatable
local dry-run while Backend/PostgreSQL credentials are not available.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .data_foundation.labeling import build_product_facet_map, label_demands, load_taxonomy
from .demand_clustering.baseline import cluster_demands, summarize_clusters


DEFAULT_TAXONOMY = Path("config/facet_taxonomy_v2_2.json")
DEFAULT_ALIAS_REGISTRY = Path("config/model1_aliases_reviewed_v2.json")
DEFAULT_OUTPUT_DIR = Path("data/processed/mvp_e2e_v2_2")


def _truthy(value: object) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes", "y", "on"}


class ReviewedAliasMatcher:
    """Resolve only APPLIED aliases using category-local codes."""

    def __init__(self, path: Path) -> None:
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.aliases = payload.get("aliases", [])
        self.version = str(payload.get("version", ""))

    def resolve(self, category_id: str, text: object) -> list[dict[str, Any]]:
        normalized = " ".join(str(text or "").casefold().split())
        matches: list[dict[str, Any]] = []
        for alias in self.aliases:
            local = alias.get("category_local_values", {}).get(str(category_id))
            if not local:
                continue
            for surface in alias.get("surfaces", []):
                candidate = " ".join(str(surface or "").casefold().split())
                if candidate and candidate in normalized:
                    matches.append({
                        "facet_name": alias["facet_name"],
                        "canonical_value": alias["canonical_value"],
                        "code": int(local["code"]),
                        "value": local.get("value", ""),
                        "matched_alias": surface,
                        "surface_length": len(candidate),
                    })
        matches.sort(key=lambda item: (-item["surface_length"], item["facet_name"], item["code"]))
        return matches


def _apply_aliases(frame: pd.DataFrame, matcher: ReviewedAliasMatcher) -> tuple[pd.DataFrame, int, int, int]:
    output = frame.copy()
    alias_hits = 0
    conflicts = 0
    corrected_hits = 0
    row_conflicts: list[bool] = []
    for index, row in output.iterrows():
        matches = matcher.resolve(str(row.get("category_id", "")), row.get("extra_requirement", ""))
        if not matches:
            row_conflicts.append(False)
            continue
        chosen_by_facet: dict[str, dict[str, Any]] = {}
        current_row_conflict = False
        for match in matches:
            if match["facet_name"] in chosen_by_facet and chosen_by_facet[match["facet_name"]]["code"] != match["code"]:
                conflicts += 1
                current_row_conflict = True
                continue
            chosen_by_facet[match["facet_name"]] = match
        current = json.loads(str(row.get("facet_values", "{}") or "{}"))
        for facet_name, match in chosen_by_facet.items():
            current[facet_name] = {"code": match["code"], "value": match["value"], "matched_alias": match["matched_alias"]}
            alias_hits += 1
            corrected_hits += int(match["canonical_value"] != "")
        output.at[index, "facet_values"] = json.dumps(current, ensure_ascii=False, separators=(",", ":"))
        row_conflicts.append(current_row_conflict)
        ordered = sorted(current.values(), key=lambda item: str(item.get("facet_name", "")))
        # The taxonomy loader already encoded the canonical facet order. Replace only
        # the affected code positions through the existing label where possible.
        label_parts = str(row.get("label", "")).split("-")
        if len(label_parts) >= len(current):
            facet_names = list(current)
            for position, facet_name in enumerate(facet_names):
                if facet_name in chosen_by_facet:
                    label_parts[position] = str(chosen_by_facet[facet_name]["code"])
            output.at[index, "label"] = "-".join(label_parts)
    output["_alias_conflict"] = row_conflicts
    return output, alias_hits, corrected_hits, conflicts


def _load_product_facets(path: Path | None) -> dict[str, list[dict[str, Any]]] | None:
    if not path or not path.is_file():
        return None
    return build_product_facet_map(pd.read_csv(path, dtype=str).fillna(""))


def label_batch(
    demands: pd.DataFrame,
    taxonomy_path: Path,
    alias_registry_path: Path,
    *,
    product_facets_path: Path | None = None,
    limit: int | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    source = demands.copy().fillna("")
    if "processed_at" not in source.columns:
        source["processed_at"] = ""
    pending = source[source["processed_at"].astype(str).str.strip().eq("")].copy()
    skipped = len(source) - len(pending)
    if limit is not None:
        pending = pending.head(limit)
    loader = load_taxonomy(taxonomy_path)
    labeled = label_demands(pending, loader, product_facet_map=_load_product_facets(product_facets_path))
    matcher = ReviewedAliasMatcher(alias_registry_path)
    labeled, alias_hits, corrected_hits, alias_conflicts = _apply_aliases(labeled, matcher)
    now = datetime.now(timezone.utc).isoformat()
    statuses: list[str] = []
    for _, row in labeled.iterrows():
        warnings = json.loads(str(row.get("label_warnings", "[]") or "[]"))
        if bool(row.get("_alias_conflict", False)):
            statuses.append("CONFLICT")
        elif warnings:
            statuses.append("PARTIALLY_RESOLVED")
        else:
            statuses.append("RESOLVED")
    labeled["pipeline_status"] = statuses
    labeled["taxonomy_version"] = "v2.2"
    labeled["alias_registry_version"] = matcher.version
    labeled["processed_at"] = labeled["pipeline_status"].isin({"RESOLVED", "PARTIALLY_RESOLVED"}).map(lambda ok: now if ok else "")
    labeled = labeled.drop(columns=["_alias_conflict"], errors="ignore")
    summary = {
        "scanned": len(source),
        "skipped": skipped,
        "resolved": statuses.count("RESOLVED"),
        "partial": statuses.count("PARTIALLY_RESOLVED"),
        "unresolved": statuses.count("UNRESOLVED"),
        "conflicts": statuses.count("CONFLICT"),
        "failed": 0,
        "alias_hits": alias_hits,
        "corrected_alias_hits": corrected_hits,
        "taxonomy_version": "v2.2",
        "elapsed_seconds": 0.0,
    }
    return labeled, summary


def run_local_e2e(
    input_path: Path,
    output_dir: Path,
    *,
    taxonomy_path: Path = DEFAULT_TAXONOMY,
    alias_registry_path: Path = DEFAULT_ALIAS_REGISTRY,
    product_facets_path: Path | None = None,
    limit: int | None = None,
    cluster_only: bool = False,
    label_only: bool = False,
) -> dict[str, Any]:
    started = time.perf_counter()
    output_dir.mkdir(parents=True, exist_ok=True)
    source = pd.read_csv(input_path, dtype=str).fillna("")
    if cluster_only:
        labeled = source
        label_summary = {"scanned": len(source), "skipped": 0, "resolved": len(source), "partial": 0, "unresolved": 0, "conflicts": 0, "failed": 0, "alias_hits": 0, "corrected_alias_hits": 0, "taxonomy_version": "v2.2", "elapsed_seconds": 0.0}
    else:
        labeled, label_summary = label_batch(source, taxonomy_path, alias_registry_path, product_facets_path=product_facets_path, limit=limit)
    labeled.to_csv(output_dir / "demand_labeled_v2_2.csv", index=False, encoding="utf-8-sig")
    eligible = labeled[labeled["pipeline_status"].isin({"RESOLVED", "PARTIALLY_RESOLVED"})].copy() if "pipeline_status" in labeled else labeled
    clustered = cluster_demands(eligible) if not label_only and not eligible.empty else eligible.assign(cluster_id=pd.Series(dtype=str))
    clusters = summarize_clusters(clustered) if not label_only and not clustered.empty else pd.DataFrame()
    clustered.to_csv(output_dir / "clustering_input_v2_2.csv", index=False, encoding="utf-8-sig")
    clustered.to_csv(output_dir / "demand_clusters_v2_2.csv", index=False, encoding="utf-8-sig")
    clusters.to_csv(output_dir / "demand_cluster_summary_v2_2.csv", index=False, encoding="utf-8-sig")
    cluster_summary = {
        "processed": 0 if label_only else len(eligible),
        "joined_existing": 0,
        "created_new": 0 if label_only else int(len(clusters)),
        "substitute_joined": 0 if label_only else int(eligible.get("is_substitutable", pd.Series(dtype=str)).astype(str).str.casefold().isin({"true", "1", "yes", "y"}).sum()) if not eligible.empty else 0,
        "skipped": len(labeled) - len(eligible),
        "failed": 0,
        "elapsed_seconds": round(time.perf_counter() - started, 6),
    }
    result = {
        "pipeline_status": "COMPLETED",
        "taxonomy_version": "v2.2",
        "labeling": label_summary,
        "clustering": cluster_summary,
        "total_elapsed_seconds": round(time.perf_counter() - started, 6),
        "outputs": {"labeled": str(output_dir / "demand_labeled_v2_2.csv"), "clustering_input": str(output_dir / "clustering_input_v2_2.csv"), "clusters": str(output_dir / "demand_cluster_summary_v2_2.csv")},
        "database": "NOT_CONNECTED_CSV_DRY_RUN",
        "backend_write": "NOT_PERFORMED_DRY_RUN",
    }
    (output_dir / "mvp_e2e_summary_v2_2.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the V2.2 local A -> B MVP pipeline")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--taxonomy", type=Path, default=DEFAULT_TAXONOMY)
    parser.add_argument("--alias-registry", type=Path, default=DEFAULT_ALIAS_REGISTRY)
    parser.add_argument("--product-facets", type=Path)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--label-only", action="store_true")
    parser.add_argument("--cluster-only", action="store_true")
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if not args.taxonomy.is_file() or not args.alias_registry.is_file():
        parser.error("V2.2 taxonomy and reviewed alias registry must exist")
    if not args.input.is_file():
        parser.error("input CSV must exist")
    if args.label_only and args.cluster_only:
        parser.error("--label-only and --cluster-only cannot be combined")
    result = run_local_e2e(args.input, args.output_dir, taxonomy_path=args.taxonomy, alias_registry_path=args.alias_registry, product_facets_path=args.product_facets, limit=args.limit, cluster_only=args.cluster_only, label_only=args.label_only)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
