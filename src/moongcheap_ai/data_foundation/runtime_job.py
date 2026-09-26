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

from .backend_contract import build_label_result_payload, post_label_results
from .demand_label_comparison import LLMLabelingError, OllamaDemandLabeler, _apply_model_result
from .labeling import (
    TaxonomyLoader,
    taxonomy_from_category_facet_rows,
)
from .part_a_runtime import run_part_a_batch
from .postgres_reader import open_read_only_postgres, read_unprocessed_demands
from .postgres_writer import open_postgres, write_label_results


def _required(source: Mapping[str, str], key: str) -> str:
    value = source.get(key, "").strip()
    if not value:
        raise ValueError(f"{key} is required")
    return value


def _first_env(source: Mapping[str, str], *keys: str, default: str = "") -> str:
    """Read the first configured value while accepting Cloud aliases."""
    for key in keys:
        value = source.get(key, "").strip()
        if value:
            return value
    return default


def _limit_llm_target(target: pd.DataFrame, max_rows: int) -> pd.DataFrame:
    """Keep the complete target; positive limits are handled as pages."""
    return target


def _llm_pages(target: pd.DataFrame, page_size: int) -> list[pd.DataFrame]:
    """Split a target into pages without dropping rows."""
    if target.empty:
        return []
    size = page_size if page_size > 0 else len(target)
    return [target.iloc[start : start + size] for start in range(0, len(target), size)]


def run_batch(
    demands: pd.DataFrame,
    taxonomy_path: Path | None,
    *,
    taxonomy_payload: dict[str, Any] | None = None,
    product_facets_path: Path | None = None,
    alias_registry_path: Path | None = None,
    rules_path: Path = Path("config/demand_constraint_rules.json"),
    compatibility_alias_registry_path: Path | None = None,
    processed_at: str | None = None,
    model2_fallback_enabled: bool = False,
    model2_fallback_model: str = "qwen2.5:7b-instruct",
    model2_fallback_endpoint: str = "http://localhost:11434",
    model2_fallback_timeout: int = 300,
    model2_fallback_batch_size: int = 5,
    llm_model: str | None = None,
    llm_endpoint: str = "http://localhost:11434",
    llm_timeout: int = 300,
    llm_batch_size: int = 5,
    llm_max_rows: int = 0,
    llm_retries: int = 2,
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
    if taxonomy_payload is None and taxonomy_path is None:
        raise ValueError("taxonomy_path or taxonomy_payload is required")
    # Product facts describe the selected catalog; they must not silently turn
    # into consumer requirements. The shared Part A parser emits only typed
    # constraints from extra_requirement and keeps unresolved requests pending.
    del product_facets_path
    labeled, _ = run_part_a_batch(
        demands,
        taxonomy_path,
        rules_path,
        alias_registry_path or Path("config/model1_aliases_reviewed_v2.json"),
        taxonomy_payload=taxonomy_payload,
        compatibility_alias_registry_path=compatibility_alias_registry_path,
        processed_at=timestamp,
        skip_processed=False,
    )
    labeled["label_status"] = labeled["status"].map({
        "PARSED": "LABELED",
        "NONE": "LABELED",
        "NOT_APPLICABLE": "LABELED",
    }).fillna("REVIEW")
    labeled["label_warnings"] = labeled["reasonCodes"]
    resolved_taxonomy = taxonomy_payload
    if resolved_taxonomy is None:
        resolved_taxonomy = TaxonomyLoader.from_path(taxonomy_path).taxonomy
    loader = TaxonomyLoader(dict(resolved_taxonomy))
    facet_map: dict[str, list[dict[str, Any]]] = {}
    fallback_summary = {"enabled": model2_fallback_enabled, "calls": 0, "accepted": 0, "review": 0}
    if model2_fallback_enabled and not labeled.empty:
        labeled, fallback_summary = _apply_model2_fallback(
            labeled,
            TaxonomyLoader(dict(resolved_taxonomy)),
            model=model2_fallback_model,
            endpoint=model2_fallback_endpoint,
            timeout=model2_fallback_timeout,
            batch_size=model2_fallback_batch_size,
        )
    if model2_fallback_enabled and not llm_model:
        llm_model = model2_fallback_model
        llm_endpoint = model2_fallback_endpoint
        llm_timeout = model2_fallback_timeout
        llm_batch_size = model2_fallback_batch_size
    llm_summary = {
        "enabled": bool(llm_model), "model": llm_model, "calls": 0,
        "applied": 0, "review": 0, "failed": 0, "retries": 0,
        "target_rows": 0, "page_count": 0,
    }
    if llm_model and not labeled.empty:
        source_by_id = {
            str(row["demand_id"]): row
            for _, row in demands.fillna("").iterrows()
            if str(row.get("demand_id", "")).strip()
        }
        target = labeled[
            labeled["label_status"].astype(str).isin(
                {"REVIEW", "CONFLICT", "PASSTHROUGH", "LABELED_WITH_REVIEW"}
            )
            & labeled["demand_id"].astype(str).isin(source_by_id)
        ]
        target = _limit_llm_target(target, llm_max_rows)
        pages = _llm_pages(target, llm_max_rows)
        llm_summary["target_rows"] = len(target)
        llm_summary["page_count"] = len(pages)
        if not target.empty:
            labeler = OllamaDemandLabeler(llm_model, endpoint=llm_endpoint, timeout=llm_timeout)

            def classify_resilient(batch: pd.DataFrame) -> tuple[dict[str, Any], str | None]:
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
                last_error = ""
                for attempt in range(max(0, llm_retries) + 1):
                    try:
                        return labeler.classify(payload, loader), None
                    except LLMLabelingError as exc:
                        last_error = str(exc)
                        if attempt < max(0, llm_retries):
                            llm_summary["retries"] += 1
                if len(batch) > 1:
                    middle = len(batch) // 2
                    left_values, left_error = classify_resilient(batch.iloc[:middle])
                    right_values, right_error = classify_resilient(batch.iloc[middle:])
                    return (
                        {**left_values, **right_values},
                        "; ".join(error for error in (left_error, right_error) if error) or None,
                    )
                return {}, last_error or "LLM batch failed"

            for page in pages:
                for start in range(0, len(page), max(1, llm_batch_size)):
                    batch = page.iloc[start : start + max(1, llm_batch_size)]
                    model_values, batch_error = classify_resilient(batch)
                    for _, result_row in batch.iterrows():
                        demand_id = str(result_row["demand_id"])
                        source = source_by_id[demand_id]
                        raw_values = model_values.get(demand_id)
                        row_index = labeled.index[labeled["demand_id"].astype(str).eq(demand_id)]
                        if not len(row_index) or raw_values is None:
                            if len(row_index):
                                target_index = row_index[0]
                                labeled.at[target_index, "llm_status"] = "FAILED"
                                labeled.at[target_index, "llm_warnings"] = json.dumps(
                                    [batch_error or "LLM returned no result for demand"], ensure_ascii=False
                                )
                            llm_summary["failed"] += 1
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
    labeled.attrs["model2_fallback"] = llm_summary
    return labeled, build_label_result_payload(labeled, processed_at=timestamp)


def _apply_model2_fallback(
    labeled: pd.DataFrame,
    loader: TaxonomyLoader,
    *,
    model: str,
    endpoint: str,
    timeout: int,
    batch_size: int,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Resolve only unresolved positive requirements with an optional Qwen call.

    The fallback never replaces a parsed rule result, never resolves explicit
    conflicts/exclusions, and never accepts a response that cannot be mapped
    entirely into the current taxonomy.  Ollama is deliberately optional so
    the normal CronJob remains deterministic when the model service is absent.
    """
    if batch_size <= 0:
        raise ValueError("model2_fallback_batch_size must be positive")
    result = labeled.copy()
    for column in ("fallback_status", "fallback_model", "fallback_warning"):
        result[column] = ""
    extra_requirement = result.get("extra_requirement", pd.Series("", index=result.index))
    candidate_mask = (
        result["status"].isin({"PASSTHROUGH", "TAXONOMY_AMBIGUOUS", "REVIEW"})
        & extra_requirement.fillna("").astype(str).str.strip().ne("")
        & ~result["effectiveRequirementMode"].astype(str).str.upper().isin({"EXCLUDE", "CONFLICT"})
    )
    candidates = result[candidate_mask]
    summary = {"enabled": True, "calls": 0, "accepted": 0, "review": int(len(candidates))}
    if candidates.empty:
        return result, summary
    labeler = OllamaDemandLabeler(model, endpoint=endpoint, timeout=timeout)
    for start in range(0, len(candidates), batch_size):
        batch = candidates.iloc[start:start + batch_size]
        rows = [
            {
                "demand_id": str(row["demand_id"]),
                "category_id": str(row["category_id"]),
                "extra_requirement": str(row.get("extra_requirement", "")),
                "product_defaults": {},
            }
            for _, row in batch.iterrows()
        ]
        try:
            model_values = labeler.classify(rows, loader)
            error = ""
        except LLMLabelingError as exc:
            model_values = {}
            error = str(exc)
        summary["calls"] = int(labeler.call_count)
        for index, row in batch.iterrows():
            demand_id = str(row["demand_id"])
            if error:
                result.at[index, "fallback_status"] = "UNAVAILABLE"
                result.at[index, "fallback_warning"] = error[:500]
                continue
            values = model_values.get(demand_id)
            if values is None:
                result.at[index, "fallback_status"] = "REVIEW"
                result.at[index, "fallback_warning"] = "MODEL_RESULT_MISSING"
                continue
            mapped, warnings = _apply_model_result(row, values, loader, [])
            non_all = [item for item in mapped.values() if int(item.get("code", 0)) != 0]
            if warnings or not non_all:
                result.at[index, "fallback_status"] = "REVIEW"
                result.at[index, "fallback_warning"] = ";".join(warnings) or "MODEL_RESULT_NOT_INFORMATIVE"
                continue
            constraints = []
            category = loader.category(str(row["category_id"])) or {}
            facets = {str(item["name"]): item for item in category.get("facets", [])}
            for facet_name, value in mapped.items():
                if int(value.get("code", 0)) == 0:
                    continue
                facet = facets.get(facet_name)
                if facet is None:
                    continue
                constraints.append({
                    "facetKey": facet_name,
                    "canonicalValue": str(value.get("value", "")),
                    "facetCode": int(facet.get("facet_id", 0)),
                    "valueCode": int(value["code"]),
                    "constraintType": "PREFER",
                    "evidence": str(row.get("extra_requirement", "")),
                })
            if not constraints:
                result.at[index, "fallback_status"] = "REVIEW"
                result.at[index, "fallback_warning"] = "MODEL_RESULT_NO_TYPED_CONSTRAINT"
                continue
            result.at[index, "constraints"] = json.dumps(constraints, ensure_ascii=False, separators=(",", ":"))
            result.at[index, "facet_values"] = json.dumps(mapped, ensure_ascii=False, separators=(",", ":"))
            result.at[index, "label"] = loader.encode(mapped)
            result.at[index, "status"] = "PARSED"
            result.at[index, "label_status"] = "LABELED"
            result.at[index, "effectiveRequirementMode"] = "STRUCTURED"
            result.at[index, "interpretation_method"] = "RULE_FIRST_QWEN_FALLBACK"
            result.at[index, "fallback_status"] = "ACCEPTED"
            result.at[index, "fallback_model"] = model
            result.at[index, "fallback_warning"] = ""
            reason_codes = json.loads(str(result.at[index, "reasonCodes"]) or "[]")
            reason_codes.append("QWEN_FALLBACK_ACCEPTED")
            result.at[index, "reasonCodes"] = json.dumps(reason_codes, ensure_ascii=False, separators=(",", ":"))
            result.at[index, "label_warnings"] = result.at[index, "reasonCodes"]
            summary["accepted"] += 1
            summary["review"] -= 1
    return result, summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the A Demand labeling batch")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--input", type=Path, help="CSV dry-run input")
    parser.add_argument("--taxonomy", type=Path)
    parser.add_argument("--product-facets", type=Path)
    parser.add_argument("--alias-registry", type=Path)
    parser.add_argument("--rules", type=Path)
    parser.add_argument("--compatibility-alias-registry", type=Path)
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
        primary_alias_registry = args.alias_registry or Path(
            source.get("A_ALIAS_REGISTRY_PATH", "config/model1_aliases_reviewed_v2.json")
        )
        compatibility_alias_registry = args.compatibility_alias_registry or Path(
            source.get("A_COMPATIBILITY_ALIAS_REGISTRY_PATH", "config/demand_constraint_aliases.json")
        )
        # The reviewed A alias export is version-bound to v2.2. A taxonomy
        # reconstructed from Backend category.facet must use its own values
        # until Backend publishes the matching reviewed alias export.
        if taxonomy_payload is not None and taxonomy_payload.get("version") != "v2.2":
            primary_alias_registry = None
            compatibility_alias_registry = None
        labeled, payload = run_batch(
            demands,
            taxonomy_path,
            taxonomy_payload=taxonomy_payload,
            product_facets_path=args.product_facets or (Path(source["A_PRODUCT_FACETS_PATH"]) if source.get("A_PRODUCT_FACETS_PATH") else None),
            alias_registry_path=primary_alias_registry,
            rules_path=args.rules or Path(source.get("A_RULES_PATH", "config/demand_constraint_rules.json")),
            compatibility_alias_registry_path=compatibility_alias_registry,
            model2_fallback_enabled=source.get("A_MODEL2_FALLBACK_ENABLED", "false").strip().lower() in {"1", "true", "yes"},
            model2_fallback_model=source.get("A_MODEL2_FALLBACK_MODEL", "qwen2.5:7b-instruct"),
            model2_fallback_endpoint=source.get("A_MODEL2_OLLAMA_BASE_URL", "http://localhost:11434"),
            model2_fallback_timeout=int(source.get("A_MODEL2_FALLBACK_TIMEOUT_SECONDS", "300")),
            model2_fallback_batch_size=int(source.get("A_MODEL2_FALLBACK_BATCH_SIZE", "5")),
            llm_model=llm_model,
            llm_endpoint=_first_env(
                source,
                "A_LLM_ENDPOINT",
                "A_MODEL2_OLLAMA_BASE_URL",
                default="http://localhost:11434",
            ),
            llm_timeout=int(_first_env(source, "A_LLM_TIMEOUT_SECONDS", "A_MODEL2_FALLBACK_TIMEOUT_SECONDS", default="300")),
            llm_batch_size=int(_first_env(source, "A_LLM_BATCH_SIZE", "A_MODEL2_FALLBACK_BATCH_SIZE", default="5")),
            llm_max_rows=int(_first_env(source, "A_LLM_MAX_ROWS", default="0")),
            llm_retries=int(_first_env(source, "A_LLM_RETRIES", "A_MODEL2_FALLBACK_RETRIES", default="2")),
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
        print(json.dumps({"status": "COMPLETED", "rows": len(labeled), "output": str(args.output), "model2Fallback": labeled.attrs.get("model2_fallback", {}), "backend": response}, ensure_ascii=False))
        return 0
    except (ValueError, RuntimeError, OSError) as error:
        print(json.dumps({"status": "FAILED", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    finally:
        if connection is not None:
            connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
