"""Connection-ready A labeling runtime with CSV dry-run support."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv

from ..demand_constraints import DemandConstraintParser
from ..mvp_pipeline import ReviewedAliasMatcher, _apply_aliases
from .backend_contract import build_label_result_payload, post_label_results
from .labeling import (
    TaxonomyLoader,
    build_product_facet_map,
    label_demands,
    load_taxonomy,
    taxonomy_from_category_facet_rows,
)
from .postgres_reader import open_read_only_postgres, read_unprocessed_demands
from .postgres_writer import open_postgres, write_label_results
from .part_a_input_policy import PartAConstraintInputPolicy
from .demand_label_comparison import LLMLabelingError, OllamaDemandLabeler, _apply_model_result


def _required(source: Mapping[str, str], key: str) -> str:
    value = source.get(key, "").strip()
    if not value:
        raise ValueError(f"{key} is required")
    return value


def _first_env(source: Mapping[str, str], *keys: str, default: str = "") -> str:
    """Read the current A names, while accepting the Cloud develop aliases."""
    for key in keys:
        value = source.get(key, "").strip()
        if value:
            return value
    return default


def run_batch(
    demands: pd.DataFrame,
    taxonomy_path: Path | None,
    *,
    taxonomy_payload: dict[str, Any] | None = None,
    product_facets_path: Path | None = None,
    alias_registry_path: Path | None = None,
    rules_path: Path | None = None,
    processed_at: str | None = None,
    llm_model: str | None = None,
    llm_endpoint: str = "http://localhost:11434",
    llm_timeout: int = 300,
    llm_batch_size: int = 5,
    llm_max_rows: int = 100,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    timestamp = processed_at or datetime.now(UTC).isoformat()
    if demands.empty:
        empty = demands.copy()
        for column in ("demand_id", "catalog_id", "category_id", "label", "facet_values", "label_status"):
            if column not in empty.columns:
                empty[column] = pd.Series(dtype="string")
        return empty, {
            "schemaVersion": "demand-label-result.v0.1",
            "processedAt": timestamp,
            "results": [],
        }
    loader = TaxonomyLoader(taxonomy_payload) if taxonomy_payload is not None else load_taxonomy(taxonomy_path)  # type: ignore[arg-type]
    facet_map = None
    if product_facets_path and product_facets_path.exists():
        facet_map = build_product_facet_map(pd.read_csv(product_facets_path, dtype=str).fillna(""))
    requirement_interpreter = None
    if rules_path and rules_path.is_file():
        parser = DemandConstraintParser.from_taxonomy(
            loader.taxonomy,
            rules_path=rules_path,
            aliases_path=alias_registry_path,
            policy_cls=PartAConstraintInputPolicy,
        )
        requirement_interpreter = parser.interpret
    labeled = label_demands(
        demands.fillna(""),
        loader,
        product_facet_map=facet_map,
        requirement_interpreter=requirement_interpreter,
    )
    if alias_registry_path and alias_registry_path.exists():
        labeled, alias_hits, corrected_alias_hits, alias_conflicts = _apply_aliases(
            labeled, ReviewedAliasMatcher(alias_registry_path)
        )
        labeled["taxonomy_version"] = "v2.2"
        labeled["alias_hits"] = alias_hits
        labeled["corrected_alias_hits"] = corrected_alias_hits
        labeled["alias_conflicts"] = alias_conflicts
    llm_summary = {"enabled": bool(llm_model), "model": llm_model, "calls": 0, "applied": 0, "review": 0}
    if llm_model and not labeled.empty:
        source_by_id = {
            str(row["demand_id"]): row
            for _, row in demands.fillna("").iterrows()
            if str(row.get("demand_id", "")).strip()
        }
        target = labeled[
            labeled["label_status"].astype(str).isin({"REVIEW", "CONFLICT", "PASSTHROUGH"})
            & labeled["demand_id"].astype(str).isin(source_by_id)
        ].head(max(0, llm_max_rows))
        if not target.empty:
            labeler = OllamaDemandLabeler(llm_model, endpoint=llm_endpoint, timeout=llm_timeout)
            for start in range(0, len(target), max(1, llm_batch_size)):
                batch = target.iloc[start : start + max(1, llm_batch_size)]
                payload = []
                for _, result_row in batch.iterrows():
                    source = source_by_id[str(result_row["demand_id"])]
                    defaults, _ = loader.product_defaults(
                        str(source.get("category_id", "")),
                        (facet_map or {}).get(str(source.get("catalog_id", "")), []),
                    )
                    payload.append({
                        "demand_id": str(source["demand_id"]),
                        "category_id": str(source.get("category_id", "")),
                        "extra_requirement": str(source.get("extra_requirement", "")),
                        "product_defaults": defaults,
                    })
                try:
                    model_values = labeler.classify(payload, loader)
                except LLMLabelingError:
                    model_values = {}
                for _, result_row in batch.iterrows():
                    demand_id = str(result_row["demand_id"])
                    source = source_by_id[demand_id]
                    raw_values = model_values.get(demand_id)
                    row_index = labeled.index[labeled["demand_id"].astype(str).eq(demand_id)]
                    if not len(row_index) or raw_values is None:
                        continue
                    defaults, warnings = _apply_model_result(
                        source,
                        raw_values,
                        loader,
                        (facet_map or {}).get(str(source.get("catalog_id", "")), []),
                    )
                    # The model output is only allowed to resolve a row when it
                    # supplied every facet and did not silently turn a non-empty
                    # requirement into ALL. Negation remains parser-owned.
                    allowed_facets = set(
                        str(item["name"])
                        for item in (loader.category(str(source.get("category_id", ""))) or {}).get("facets", [])
                    )
                    negative_markers = ("피하고", "제외", "금지", "없는", "않", "안 ")
                    requirement = str(source.get("extra_requirement", ""))
                    supplied = {str(key) for key in raw_values}
                    if allowed_facets - supplied:
                        warnings.append("LLM omitted one or more taxonomy facets")
                    if requirement.strip() and not any(
                        int(value.get("code", 0) or 0) != 0 for value in defaults.values()
                    ):
                        warnings.append("LLM returned only ALL for a non-empty requirement")
                    if any(marker in requirement for marker in negative_markers):
                        warnings.append("negative constraints remain parser-owned")
                    target_index = row_index[0]
                    if warnings:
                        labeled.at[target_index, "llm_status"] = "REVIEW"
                        labeled.at[target_index, "llm_warnings"] = json.dumps(warnings, ensure_ascii=False)
                        llm_summary["review"] += 1
                        continue
                    labeled.at[target_index, "label"] = loader.encode(defaults)
                    labeled.at[target_index, "facet_values"] = json.dumps(defaults, ensure_ascii=False, separators=(",", ":"))
                    labeled.at[target_index, "label_status"] = "PARSED"
                    labeled.at[target_index, "interpretation_method"] = "RULE_LLM_FALLBACK"
                    labeled.at[target_index, "llm_status"] = "APPLIED"
                    llm_summary["applied"] += 1
            llm_summary["calls"] = labeler.call_count
    return labeled, build_label_result_payload(labeled, processed_at=timestamp)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the A Demand labeling batch")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--input", type=Path, help="CSV dry-run input")
    parser.add_argument("--taxonomy", type=Path)
    parser.add_argument("--product-facets", type=Path)
    parser.add_argument("--alias-registry", type=Path)
    parser.add_argument("--rules", type=Path)
    parser.add_argument("--output", type=Path, default=Path("data/processed/demands/runtime_labeled_v0.csv"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--write-db",
        action="store_true",
        help="write completed labels directly to PostgreSQL; mutually exclusive with Backend submission",
    )
    args = parser.parse_args(argv)
    if args.env_file:
        load_dotenv(args.env_file, override=False)
    source = os.environ
    taxonomy_path = args.taxonomy or Path(source.get("A_TAXONOMY_PATH", "config/facet_taxonomy_v2_2.json"))
    rules_path = args.rules or Path(source.get("A_RULES_PATH", "config/demand_constraint_rules.json"))
    llm_enabled = _first_env(
        source,
        "A_LLM_ENABLED",
        "A_MODEL2_FALLBACK_ENABLED",
        default="false",
    ).lower() in {"1", "true", "yes", "on"}
    llm_model = _first_env(source, "A_LLM_MODEL", "A_MODEL2_FALLBACK_MODEL") if llm_enabled else None

    connection = None
    write_to_database = args.write_db or source.get("A_WRITE_DATABASE", "").strip().lower() in {"1", "true", "yes"}
    if args.dry_run and write_to_database:
        raise SystemExit("--dry-run cannot be combined with --write-db or A_WRITE_DATABASE=true")
    try:
        if args.input:
            demands = pd.read_csv(args.input, dtype=str)
        else:
            connection = (
                open_postgres(_required(source, "A_DATABASE_URL"))
                if write_to_database
                else open_read_only_postgres(_required(source, "A_DATABASE_URL"))
            )
            demands = read_unprocessed_demands(connection)
        taxonomy_payload = None
        if not args.input and "category_facet" in demands.columns and not demands.empty:
            taxonomy_payload = taxonomy_from_category_facet_rows(demands)
        if taxonomy_payload is None and not demands.empty and not taxonomy_path.is_file():
            raise SystemExit(f"taxonomy file not found: {taxonomy_path}")
        labeled, payload = run_batch(
            demands,
            taxonomy_path,
            taxonomy_payload=taxonomy_payload,
            product_facets_path=args.product_facets or (Path(source["A_PRODUCT_FACETS_PATH"]) if source.get("A_PRODUCT_FACETS_PATH") else None),
            alias_registry_path=args.alias_registry or Path(source.get("A_ALIAS_REGISTRY_PATH", "config/model1_aliases_reviewed_v2.json")),
            rules_path=rules_path,
            llm_model=llm_model,
            llm_endpoint=_first_env(
                source,
                "A_LLM_ENDPOINT",
                "A_MODEL2_OLLAMA_BASE_URL",
                default="http://localhost:11434",
            ),
            llm_timeout=int(_first_env(source, "A_LLM_TIMEOUT_SECONDS", "A_MODEL2_FALLBACK_TIMEOUT_SECONDS", default="300")),
            llm_batch_size=int(_first_env(source, "A_LLM_BATCH_SIZE", "A_MODEL2_FALLBACK_BATCH_SIZE", default="5")),
            llm_max_rows=int(_first_env(source, "A_LLM_MAX_ROWS", default="100")),
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        labeled.to_csv(args.output, index=False, encoding="utf-8-sig")
        if write_to_database:
            if connection is None:
                connection = open_postgres(_required(source, "A_DATABASE_URL"))
            written = write_label_results(
                connection,
                labeled.to_dict(orient="records"),
                processed_at=payload["processedAt"],
            )
            response = {"status": "DB_APPLIED", "updatedCount": written}
        elif not args.dry_run:
            response = post_label_results(
                _required(source, "A_BACKEND_BASE_URL"),
                _required(source, "A_BACKEND_INTERNAL_KEY"),
                _required(source, "A_LABEL_RESULT_ENDPOINT"),
                payload,
                timeout_seconds=int(source.get("A_BACKEND_HTTP_TIMEOUT_SECONDS", "15")),
            )
        else:
            response = {"status": "DRY_RUN"}
        print(json.dumps({"status": "COMPLETED", "rows": len(labeled), "output": str(args.output), "backend": response}, ensure_ascii=False))
        return 0
    except (ValueError, RuntimeError, OSError) as error:
        print(json.dumps({"status": "FAILED", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    finally:
        if connection is not None:
            connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
