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
from .demand_label_comparison import (
    LLMLabelingError,
    OllamaDemandLabeler,
    _apply_model_result,
    _has_non_positive_requirement_marker,
    ensure_ollama_model_available,
)
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


def _labeling_status_counts(labeled: pd.DataFrame) -> dict[str, int]:
    """Return stable status counts for batch logs without exposing demand text."""
    if "label_status" not in labeled.columns:
        return {}
    counts = labeled["label_status"].fillna("").astype(str).str.upper().value_counts()
    return {str(status): int(count) for status, count in sorted(counts.items())}


def _has_ambiguous_or_failed_analysis(row: Mapping[str, Any]) -> bool:
    """Do not ask a second model to override explicitly ambiguous/failed parses."""
    status = str(row.get("status", "")).strip().upper()
    if status in {"CONFLICT", "TAXONOMY_AMBIGUOUS"}:
        return True
    raw_codes = row.get("reasonCodes", "[]")
    try:
        codes = json.loads(str(raw_codes or "[]"))
    except (TypeError, json.JSONDecodeError):
        return True
    if not isinstance(codes, list):
        return True
    blocked_markers = (
        "AMBIGUOUS",
        "COLLISION",
        "CONFLICT",
        "PARSER_EXCEPTION",
        "INVALID_IS_SUBSTITUTABLE",
    )
    return any(
        any(marker in str(code).upper() for marker in blocked_markers) for code in codes
    )


def _has_complete_product_baseline(
    row: Mapping[str, Any],
    loader: TaxonomyLoader,
    defaults_by_demand: Mapping[str, dict[str, dict[str, Any]]],
) -> bool:
    demand_id = str(row.get("demand_id", "")).strip()
    category_id = str(row.get("category_id", "")).strip()
    category = loader.categories.get(category_id)
    if not demand_id or category is None:
        return False
    defaults = defaults_by_demand.get(demand_id, {})
    facets = {str(facet.get("name", "")): facet for facet in category.get("facets", [])}
    if not facets or set(defaults) != set(facets):
        return False
    for facet_name, value in defaults.items():
        try:
            code = int(value.get("code", -1))
        except (AttributeError, TypeError, ValueError):
            return False
        allowed = {
            int(item.get("code", -1)): str(item.get("value", ""))
            for item in facets[facet_name].get("values", [])
        }
        if code <= 0 or allowed.get(code) != str(value.get("value", "")):
            return False
    return True


def _load_runtime_product_facet_map(
    path: Path | None,
) -> dict[str, list[dict[str, Any]]]:
    """Load product defaults indexed only by actual Backend catalog IDs."""
    if path is None:
        return {}
    if not path.is_file():
        raise FileNotFoundError(f"product Facet mapping file not found: {path}")
    if path.suffix.lower() != ".csv":
        raise ValueError("runtime product Facet mapping must be a CSV file")
    try:
        frame = pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")
    except (OSError, pd.errors.ParserError) as error:
        raise RuntimeError(f"failed to read product Facet mapping: {path}") from error
    required = {
        "backend_catalog_id",
        "category_id",
        "facet_name",
        "mapping_status",
        "value",
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(
            "runtime product Facet mapping is missing columns: "
            + ", ".join(sorted(missing))
        )
    if frame.empty:
        raise ValueError("runtime product Facet mapping is empty")
    for column in (
        "backend_catalog_id",
        "category_id",
        "facet_name",
        "mapping_status",
    ):
        frame[column] = frame[column].astype(str).str.strip()
        if frame[column].eq("").any():
            raise ValueError(f"runtime product Facet mapping has empty {column}")
    frame["mapping_status"] = frame["mapping_status"].str.upper()
    statuses = {"MAPPED", "UNKNOWN", "AMBIGUOUS", "UNMAPPED", "UNMATCHED_CATEGORY"}
    actual_statuses = set(frame["mapping_status"].str.strip().str.upper())
    unsupported = actual_statuses - statuses
    if unsupported:
        raise ValueError(
            "runtime product Facet mapping has unsupported statuses: "
            + ", ".join(sorted(unsupported))
        )
    mapped_without_value = frame["mapping_status"].str.strip().str.upper().eq(
        "MAPPED"
    ) & frame["value"].str.strip().eq("")
    if mapped_without_value.any():
        raise ValueError("MAPPED product Facet rows must have a non-empty value")
    if not frame["backend_catalog_id"].str.fullmatch(r"[1-9][0-9]*").all():
        raise ValueError(
            "backend_catalog_id must contain positive numeric product_catalog.id values"
        )

    result: dict[str, list[dict[str, Any]]] = {}
    for catalog_id, group in frame.groupby("backend_catalog_id", sort=False):
        categories = set(group["category_id"].str.strip())
        if len(categories) != 1:
            raise ValueError(
                f"backend_catalog_id has conflicting taxonomy categories: {catalog_id}"
            )
        facet_statuses = group.groupby("facet_name")["mapping_status"].nunique()
        if facet_statuses.gt(1).any():
            raise ValueError(
                f"backend_catalog_id has conflicting mapping statuses for a Facet: {catalog_id}"
            )
        result[str(catalog_id).strip()] = group.to_dict(orient="records")
    # Only the explicitly named Backend namespace is indexed; Seed/source IDs
    # cannot accidentally collide with Backend product_catalog.id.
    return result


def run_batch(
    demands: pd.DataFrame,
    taxonomy_path: Path | None,
    *,
    taxonomy_payload: dict[str, Any] | None = None,
    product_facets_path: Path | None = None,
    product_facet_map: dict[str, list[dict[str, Any]]] | None = None,
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
        for column in (
            "demand_id",
            "catalog_id",
            "category_id",
            "label",
            "facet_values",
            "label_status",
        ):
            if column not in empty.columns:
                empty[column] = pd.Series(dtype="string")
        return empty, {
            "schemaVersion": "demand-label-result.v0.1",
            "processedAt": timestamp,
            "results": [],
        }
    if taxonomy_payload is None and taxonomy_path is None:
        raise ValueError("taxonomy_path or taxonomy_payload is required")
    if product_facets_path is not None and product_facet_map is not None:
        raise ValueError("provide product_facets_path or product_facet_map, not both")
    if product_facets_path is not None:
        product_facet_map = _load_runtime_product_facet_map(product_facets_path)
    labeled, _ = run_part_a_batch(
        demands,
        taxonomy_path,
        rules_path,
        alias_registry_path or Path("config/model1_aliases_reviewed_v2.json"),
        taxonomy_payload=taxonomy_payload,
        compatibility_alias_registry_path=compatibility_alias_registry_path,
        skip_processed=False,
    )
    if "extra_requirement" not in labeled.columns:
        labeled["extra_requirement"] = ""
    parser_status = (
        labeled["status"]
        .map(
            {
                "PARSED": "LABELED",
                "NONE": "LABELED",
                "NOT_APPLICABLE": "LABELED",
            }
        )
        .fillna("REVIEW")
    )
    labeled["label_status"] = parser_status
    labeled["label_warnings"] = labeled["reasonCodes"]
    resolved_taxonomy = taxonomy_payload
    if resolved_taxonomy is None:
        resolved_taxonomy = TaxonomyLoader.from_path(taxonomy_path).taxonomy
    loader = TaxonomyLoader(dict(resolved_taxonomy))
    source_by_id = {
        str(row["demand_id"]): row
        for _, row in demands.fillna("").iterrows()
        if str(row.get("demand_id", "")).strip()
    }
    product_defaults_by_demand: dict[str, dict[str, dict[str, Any]]] = {}
    product_default_warnings: dict[str, list[str]] = {}
    for result_index, result_row in labeled.iterrows():
        demand_id = str(result_row.get("demand_id", ""))
        source = source_by_id.get(demand_id, result_row)
        category_id = str(source.get("category_id", ""))
        catalog_id = str(source.get("catalog_id", "")).strip()
        product_rows = (product_facet_map or {}).get(catalog_id, [])
        category_facets = (loader.categories.get(category_id) or {}).get("facets", [])
        expected_facets = {str(facet.get("name", "")) for facet in category_facets}
        supplied_facets = {
            str(row.get("facet_name", "")).strip() for row in product_rows
        }
        missing_facets = expected_facets - supplied_facets
        unexpected_facets = supplied_facets - expected_facets
        profile_categories = {
            str(row.get("category_id", "")).strip() for row in product_rows
        }
        unresolved_profile_statuses = {
            str(row.get("mapping_status", "")).strip().upper() for row in product_rows
        } - {"MAPPED"}
        defaults, warnings = loader.product_defaults(category_id, product_rows)
        invalid_values = bool(warnings)
        if (
            not defaults
            or not product_rows
            or missing_facets
            or unexpected_facets
            or profile_categories != {category_id}
            or unresolved_profile_statuses
            or invalid_values
        ):
            # Never substitute inferred text or category-wide ALL for a missing
            # product profile: that would falsely complete a product baseline.
            if not product_rows:
                warnings = [
                    f"product Facet profile not found for catalog_id={catalog_id}"
                ]
            elif missing_facets:
                warnings.append(
                    "product Facet profile is incomplete: "
                    + ", ".join(sorted(missing_facets))
                )
            if unexpected_facets:
                warnings.append(
                    "product Facet profile has unknown facets: "
                    + ", ".join(sorted(unexpected_facets))
                )
            if product_rows and profile_categories != {category_id}:
                warnings.append(
                    "product Facet profile category does not match demand taxonomy"
                )
            if unresolved_profile_statuses:
                warnings.append(
                    "product Facet profile contains unresolved mapping statuses: "
                    + ", ".join(sorted(unresolved_profile_statuses))
                )
            labeled.at[result_index, "label_status"] = "REVIEW"
            labeled.at[result_index, "label"] = ""
            labeled.at[result_index, "facet_values"] = "{}"
            labeled.at[result_index, "processed_at"] = ""
            labeled.at[result_index, "label_source"] = ""
            product_default_warnings[demand_id] = warnings
            continue
        product_defaults_by_demand[demand_id] = defaults
        product_default_warnings[demand_id] = warnings
        final_values = {name: dict(value) for name, value in defaults.items()}
        overrides: dict[str, set[tuple[int, str]]] = {}
        if str(result_row.get("status", "")).upper() == "PARSED":
            try:
                constraints = json.loads(
                    str(result_row.get("constraints", "[]")) or "[]"
                )
            except json.JSONDecodeError:
                constraints = []
            if isinstance(constraints, list):
                for constraint in constraints:
                    if not isinstance(constraint, dict) or str(
                        constraint.get("constraintType", "")
                    ).upper() not in {"MUST", "PREFER"}:
                        continue
                    facet_name = str(constraint.get("facetKey", ""))
                    try:
                        code = int(constraint.get("valueCode", 0))
                    except (TypeError, ValueError):
                        continue
                    value_text = str(constraint.get("canonicalValue", ""))
                    if facet_name in final_values and code > 0:
                        overrides.setdefault(facet_name, set()).add((code, value_text))
        for facet_name, candidates in overrides.items():
            if len(candidates) != 1:
                continue
            code, value_text = next(iter(candidates))
            facet = next(
                (
                    item
                    for item in (loader.category(category_id) or {}).get("facets", [])
                    if str(item.get("name", "")) == facet_name
                ),
                None,
            )
            allowed = next(
                (
                    item
                    for item in (facet or {}).get("values", [])
                    if int(item.get("code", -1)) == code
                ),
                None,
            )
            if allowed is not None:
                final_values[facet_name] = {
                    "code": code,
                    "value": allowed.get("value", value_text),
                    "matched_alias": "DEMAND_REQUIREMENT",
                }
        labeled.at[result_index, "facet_values"] = json.dumps(
            final_values, ensure_ascii=False, separators=(",", ":")
        )
        labeled.at[result_index, "label"] = loader.encode(final_values)
        labeled.at[result_index, "label_status"] = "LABELED"
        labeled.at[result_index, "processed_at"] = timestamp
        labeled.at[result_index, "label_source"] = (
            "PRODUCT_DEFAULT_PLUS_DEMAND"
            if any(
                value.get("matched_alias") == "DEMAND_REQUIREMENT"
                for value in final_values.values()
            )
            else "PRODUCT_DEFAULT"
        )
        try:
            diagnostic_warnings = json.loads(
                str(result_row.get("reasonCodes", "[]")) or "[]"
            )
        except json.JSONDecodeError:
            diagnostic_warnings = []
        if not isinstance(diagnostic_warnings, list):
            diagnostic_warnings = []
        diagnostic_warnings.extend(product_default_warnings[demand_id])
        diagnostic_warnings = list(
            dict.fromkeys(str(item) for item in diagnostic_warnings)
        )
        labeled.at[result_index, "label_warnings"] = json.dumps(
            diagnostic_warnings, ensure_ascii=False, separators=(",", ":")
        )
    fallback_summary = {
        "enabled": model2_fallback_enabled,
        "calls": 0,
        "accepted": 0,
        "review": 0,
    }
    if model2_fallback_enabled and not labeled.empty:
        labeled, fallback_summary = _apply_model2_fallback(
            labeled,
            TaxonomyLoader(dict(resolved_taxonomy)),
            model=model2_fallback_model,
            endpoint=model2_fallback_endpoint,
            timeout=model2_fallback_timeout,
            batch_size=model2_fallback_batch_size,
            product_defaults_by_demand=product_defaults_by_demand,
        )
    if model2_fallback_enabled and not llm_model:
        llm_model = model2_fallback_model
        llm_endpoint = model2_fallback_endpoint
        llm_timeout = model2_fallback_timeout
        llm_batch_size = model2_fallback_batch_size
    llm_summary = {
        "enabled": bool(llm_model),
        "model": llm_model,
        "calls": 0,
        "applied": 0,
        "review": 0,
        "failed": 0,
        "retries": 0,
        "target_rows": 0,
        "page_count": 0,
    }
    if llm_model and not labeled.empty:
        target = labeled[
            labeled["status"].astype(str).isin({"REVIEW", "PASSTHROUGH"})
            & labeled["label_status"].astype(str).eq("LABELED")
            & labeled["demand_id"].astype(str).isin(source_by_id)
            & ~labeled["effectiveRequirementMode"]
            .astype(str)
            .str.upper()
            .isin({"EXCLUDE", "CONFLICT"})
            & ~labeled["extra_requirement"].map(_has_non_positive_requirement_marker)
            & ~labeled.get("reasonCodes", pd.Series("", index=labeled.index))
            .fillna("")
            .astype(str)
            .str.contains("MULTIPLE_VALUES_SAME_FACET_UNRESOLVED", regex=False)
            & ~labeled.apply(_has_ambiguous_or_failed_analysis, axis=1)
            # The first fallback already validated these rows. A second
            # invocation must not override its REVIEW/UNAVAILABLE decision.
            & labeled.get("fallback_status", pd.Series("", index=labeled.index)).eq("")
        ]
        target = _limit_llm_target(target, llm_max_rows)
        pages = _llm_pages(target, llm_max_rows)
        llm_summary["target_rows"] = len(target)
        llm_summary["page_count"] = len(pages)
        if not target.empty:
            labeler = OllamaDemandLabeler(
                llm_model, endpoint=llm_endpoint, timeout=llm_timeout
            )

            def classify_resilient(
                batch: pd.DataFrame,
            ) -> tuple[dict[str, Any], str | None]:
                payload = []
                for _, result_row in batch.iterrows():
                    source = source_by_id[str(result_row["demand_id"])]
                    defaults = product_defaults_by_demand.get(
                        str(source.get("demand_id", "")), {}
                    )
                    payload.append(
                        {
                            "demand_id": str(source["demand_id"]),
                            "category_id": str(source.get("category_id", "")),
                            "extra_requirement": str(
                                source.get("extra_requirement", "")
                            ),
                            "product_defaults": defaults,
                        }
                    )
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
                        "; ".join(error for error in (left_error, right_error) if error)
                        or None,
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
                        row_index = labeled.index[
                            labeled["demand_id"].astype(str).eq(demand_id)
                        ]
                        if not len(row_index) or raw_values is None:
                            if len(row_index):
                                target_index = row_index[0]
                                labeled.at[target_index, "llm_status"] = "FAILED"
                                labeled.at[target_index, "llm_warnings"] = json.dumps(
                                    [
                                        batch_error
                                        or "LLM returned no result for demand"
                                    ],
                                    ensure_ascii=False,
                                )
                            llm_summary["failed"] += 1
                            continue
                        baseline = product_defaults_by_demand.get(demand_id, {})
                        defaults, warnings = _apply_model_result(
                            source,
                            raw_values,
                            loader,
                            baseline_values=baseline,
                        )
                        # The model output is only allowed to resolve a row when it
                        # supplied every facet and did not silently turn a non-empty
                        # requirement into ALL. Negation remains parser-owned.
                        allowed_facets = {
                            str(item["name"])
                            for item in (
                                loader.category(str(source.get("category_id", "")))
                                or {}
                            ).get("facets", [])
                        }
                        requirement = str(source.get("extra_requirement", ""))
                        supplied = {str(key) for key in raw_values}
                        if allowed_facets - supplied:
                            warnings.append("LLM omitted one or more taxonomy facets")
                        if requirement.strip() and not any(
                            int(value.get("code", 0) or 0) != 0
                            for value in defaults.values()
                        ):
                            warnings.append(
                                "LLM returned only ALL for a non-empty requirement"
                            )
                        target_index = row_index[0]
                        if warnings:
                            labeled.at[target_index, "llm_status"] = "REVIEW"
                            labeled.at[target_index, "llm_warnings"] = json.dumps(
                                warnings, ensure_ascii=False
                            )
                            llm_summary["review"] += 1
                            continue
                        merged = {name: dict(value) for name, value in baseline.items()}
                        for facet_name, value in defaults.items():
                            if (
                                value.get("matched_alias") == "LLM"
                                and int(value.get("code", 0) or 0) > 0
                            ):
                                merged[facet_name] = value
                        labeled.at[target_index, "label"] = loader.encode(merged)
                        labeled.at[target_index, "facet_values"] = json.dumps(
                            merged, ensure_ascii=False, separators=(",", ":")
                        )
                        labeled.at[target_index, "label_status"] = "LABELED"
                        labeled.at[target_index, "label_source"] = (
                            "PRODUCT_DEFAULT_PLUS_LLM"
                        )
                        labeled.at[target_index, "interpretation_method"] = (
                            "RULE_LLM_FALLBACK"
                        )
                        labeled.at[target_index, "llm_status"] = "APPLIED"
                        llm_summary["applied"] += 1
            llm_summary["calls"] = labeler.call_count
    if model2_fallback_enabled:
        llm_summary["calls"] += int(fallback_summary["calls"])
        llm_summary["applied"] += int(fallback_summary["accepted"])
        fallback_status = labeled.get(
            "fallback_status", pd.Series("", index=labeled.index)
        )
        llm_summary["failed"] += int(fallback_status.eq("UNAVAILABLE").sum())
        llm_summary["review"] += int(fallback_status.eq("REVIEW").sum())
        llm_summary["target_rows"] += int(fallback_status.ne("").sum())
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
    product_defaults_by_demand: dict[str, dict[str, dict[str, Any]]] | None = None,
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
    extra_requirement = result.get(
        "extra_requirement", pd.Series("", index=result.index)
    )
    valid_baseline = result.apply(
        lambda row: _has_complete_product_baseline(
            row, loader, product_defaults_by_demand or {}
        ),
        axis=1,
    )
    candidate_mask = (
        result["status"].isin({"PASSTHROUGH", "REVIEW"})
        & result.get("label_status", pd.Series("", index=result.index))
        .astype(str)
        .eq("LABELED")
        & valid_baseline
        & extra_requirement.fillna("").astype(str).str.strip().ne("")
        & ~result["effectiveRequirementMode"]
        .astype(str)
        .str.upper()
        .isin({"EXCLUDE", "CONFLICT"})
    )
    blocked_analysis = result.apply(_has_ambiguous_or_failed_analysis, axis=1)
    multi_value_unresolved = (
        result.get("reasonCodes", pd.Series("", index=result.index))
        .fillna("")
        .astype(str)
        .str.contains("MULTIPLE_VALUES_SAME_FACET_UNRESOLVED", regex=False)
    )
    non_positive_candidates = candidate_mask & extra_requirement.map(
        _has_non_positive_requirement_marker
    )
    multi_value_candidates = candidate_mask & multi_value_unresolved
    failed_or_ambiguous_candidates = candidate_mask & blocked_analysis
    result.loc[non_positive_candidates, "fallback_status"] = "REVIEW"
    result.loc[non_positive_candidates, "fallback_warning"] = (
        "negative or contrastive constraints remain parser-owned"
    )
    result.loc[multi_value_candidates, "fallback_status"] = "REVIEW"
    result.loc[multi_value_candidates, "fallback_warning"] = (
        "multiple values in one facet cannot be represented by a single label"
    )
    result.loc[failed_or_ambiguous_candidates, "fallback_status"] = "REVIEW"
    result.loc[failed_or_ambiguous_candidates, "fallback_warning"] = (
        "ambiguous or failed parser result retains product Facet baseline"
    )
    blocked_candidates = (
        non_positive_candidates
        | multi_value_candidates
        | failed_or_ambiguous_candidates
    )
    candidates = result[candidate_mask & ~blocked_candidates]
    summary = {
        "enabled": True,
        "calls": 0,
        "accepted": 0,
        "review": len(candidates) + int(blocked_candidates.sum()),
    }
    if candidates.empty:
        return result, summary
    labeler = OllamaDemandLabeler(model, endpoint=endpoint, timeout=timeout)
    for start in range(0, len(candidates), batch_size):
        batch = candidates.iloc[start : start + batch_size]
        rows = [
            {
                "demand_id": str(row["demand_id"]),
                "category_id": str(row["category_id"]),
                "extra_requirement": str(row.get("extra_requirement", "")),
                "product_defaults": (product_defaults_by_demand or {}).get(
                    str(row.get("demand_id", "")), {}
                ),
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
            category = loader.category(str(row["category_id"])) or {}
            expected_facets = {
                str(facet.get("name", ""))
                for facet in category.get("facets", [])
                if str(facet.get("name", "")).strip()
            }
            supplied_facets = {str(name).strip() for name in values}
            if supplied_facets != expected_facets:
                result.at[index, "fallback_status"] = "REVIEW"
                result.at[index, "fallback_warning"] = (
                    "LLM facet keys do not match the category taxonomy"
                )
                continue
            baseline = (product_defaults_by_demand or {}).get(demand_id, {})
            mapped, warnings = _apply_model_result(
                row, values, loader, baseline_values=baseline
            )
            overrides = {
                name: value
                for name, value in mapped.items()
                if value.get("matched_alias") == "LLM"
                and int(value.get("code", 0) or 0) > 0
            }
            if warnings or not overrides:
                result.at[index, "fallback_status"] = "REVIEW"
                result.at[index, "fallback_warning"] = (
                    ";".join(warnings) or "MODEL_RESULT_NOT_INFORMATIVE"
                )
                continue
            constraints = []
            category = loader.category(str(row["category_id"])) or {}
            facets = {str(item["name"]): item for item in category.get("facets", [])}
            for facet_name, value in overrides.items():
                facet = facets.get(facet_name)
                if facet is None:
                    continue
                constraints.append(
                    {
                        "facetKey": facet_name,
                        "canonicalValue": str(value.get("value", "")),
                        "facetCode": int(facet.get("facet_id", 0)),
                        "valueCode": int(value["code"]),
                        "constraintType": "PREFER",
                        "evidence": str(row.get("extra_requirement", "")),
                    }
                )
            if not constraints:
                result.at[index, "fallback_status"] = "REVIEW"
                result.at[index, "fallback_warning"] = (
                    "MODEL_RESULT_NO_TYPED_CONSTRAINT"
                )
                continue
            result.at[index, "constraints"] = json.dumps(
                constraints, ensure_ascii=False, separators=(",", ":")
            )
            merged = {name: dict(value) for name, value in baseline.items()}
            merged.update(overrides)
            result.at[index, "facet_values"] = json.dumps(
                merged, ensure_ascii=False, separators=(",", ":")
            )
            result.at[index, "label"] = loader.encode(merged)
            result.at[index, "status"] = "PARSED"
            result.at[index, "label_status"] = "LABELED"
            result.at[index, "label_source"] = "PRODUCT_DEFAULT_PLUS_LLM"
            result.at[index, "effectiveRequirementMode"] = "STRUCTURED"
            result.at[index, "interpretation_method"] = "RULE_FIRST_QWEN_FALLBACK"
            result.at[index, "fallback_status"] = "ACCEPTED"
            result.at[index, "fallback_model"] = model
            result.at[index, "fallback_warning"] = ""
            reason_codes = json.loads(str(result.at[index, "reasonCodes"]) or "[]")
            reason_codes.append("QWEN_FALLBACK_ACCEPTED")
            result.at[index, "reasonCodes"] = json.dumps(
                reason_codes, ensure_ascii=False, separators=(",", ":")
            )
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
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/processed/demands/runtime_labeled_v0.csv"),
    )
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
    taxonomy_path = args.taxonomy or Path(
        source.get("A_TAXONOMY_PATH", "config/facet_taxonomy_v2_2.json")
    )

    model2_fallback_enabled = source.get(
        "A_MODEL2_FALLBACK_ENABLED", "false"
    ).strip().lower() in {"1", "true", "yes"}
    llm_enabled = source.get("A_LLM_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    llm_model = (
        _first_env(
            source,
            "A_LLM_MODEL",
            "A_MODEL2_FALLBACK_MODEL",
            default="qwen2.5:7b-instruct",
        )
        if (llm_enabled or model2_fallback_enabled)
        else None
    )
    llm_endpoint = _first_env(
        source,
        "A_LLM_ENDPOINT",
        "A_MODEL2_OLLAMA_BASE_URL",
        default="http://localhost:11434",
    )
    if llm_model:
        try:
            preflight_timeout = int(
                _first_env(source, "A_LLM_PREFLIGHT_TIMEOUT_SECONDS", default="10")
            )
            if preflight_timeout <= 0:
                raise ValueError("A_LLM_PREFLIGHT_TIMEOUT_SECONDS must be positive")
            ensure_ollama_model_available(
                llm_endpoint, llm_model, timeout=preflight_timeout
            )
        except LLMLabelingError as error:
            # Explicit product Facet profiles remain a valid fallback when the
            # optional model worker is unavailable. Disable only model calls.
            print(
                json.dumps(
                    {
                        "status": "MODEL_UNAVAILABLE_USING_PRODUCT_DEFAULTS",
                        "warning": str(error),
                    },
                    ensure_ascii=False,
                ),
                file=sys.stderr,
            )
            llm_model = None
            llm_enabled = False
            model2_fallback_enabled = False
        except ValueError as error:
            print(
                json.dumps(
                    {"status": "FAILED", "error": str(error)}, ensure_ascii=False
                ),
                file=sys.stderr,
            )
            return 1

    connection = None
    write_to_database = args.write_db or source.get(
        "A_WRITE_DATABASE", ""
    ).strip().lower() in {"1", "true", "yes"}
    if args.dry_run and write_to_database:
        raise SystemExit(
            "--dry-run cannot be combined with --write-db or A_WRITE_DATABASE=true"
        )
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
        if (
            taxonomy_payload is None
            and not demands.empty
            and not taxonomy_path.is_file()
        ):
            raise SystemExit(f"taxonomy file not found: {taxonomy_path}")
        product_facets_path = args.product_facets or (
            Path(source["A_PRODUCT_FACETS_PATH"])
            if source.get("A_PRODUCT_FACETS_PATH", "").strip()
            else None
        )
        if not demands.empty and product_facets_path is None:
            raise ValueError(
                "A_PRODUCT_FACETS_PATH or --product-facets is required for a non-empty batch; "
                "the original product Facet profile must be supplied"
            )
        primary_alias_registry = args.alias_registry or Path(
            source.get(
                "A_ALIAS_REGISTRY_PATH", "config/model1_aliases_reviewed_v2.json"
            )
        )
        compatibility_alias_registry = args.compatibility_alias_registry or Path(
            source.get(
                "A_COMPATIBILITY_ALIAS_REGISTRY_PATH",
                "config/demand_constraint_aliases.json",
            )
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
            product_facets_path=product_facets_path,
            alias_registry_path=primary_alias_registry,
            rules_path=args.rules
            or Path(source.get("A_RULES_PATH", "config/demand_constraint_rules.json")),
            compatibility_alias_registry_path=compatibility_alias_registry,
            model2_fallback_enabled=model2_fallback_enabled,
            model2_fallback_model=source.get(
                "A_MODEL2_FALLBACK_MODEL", "qwen2.5:7b-instruct"
            ),
            model2_fallback_endpoint=source.get(
                "A_MODEL2_OLLAMA_BASE_URL", "http://localhost:11434"
            ),
            model2_fallback_timeout=int(
                source.get("A_MODEL2_FALLBACK_TIMEOUT_SECONDS", "300")
            ),
            model2_fallback_batch_size=int(
                source.get("A_MODEL2_FALLBACK_BATCH_SIZE", "5")
            ),
            llm_model=llm_model if llm_enabled else None,
            llm_endpoint=llm_endpoint,
            llm_timeout=int(
                _first_env(
                    source,
                    "A_LLM_TIMEOUT_SECONDS",
                    "A_MODEL2_FALLBACK_TIMEOUT_SECONDS",
                    default="300",
                )
            ),
            llm_batch_size=int(
                _first_env(
                    source,
                    "A_LLM_BATCH_SIZE",
                    "A_MODEL2_FALLBACK_BATCH_SIZE",
                    default="5",
                )
            ),
            llm_max_rows=int(_first_env(source, "A_LLM_MAX_ROWS", default="0")),
            llm_retries=int(
                _first_env(
                    source, "A_LLM_RETRIES", "A_MODEL2_FALLBACK_RETRIES", default="2"
                )
            ),
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
        status_counts = _labeling_status_counts(labeled)
        print(
            json.dumps(
                {
                    "status": "COMPLETED",
                    "rows": len(labeled),
                    "labelingStatusCounts": status_counts,
                    "reviewCount": status_counts.get("REVIEW", 0),
                    "output": str(args.output),
                    "model2Fallback": labeled.attrs.get("model2_fallback", {}),
                    "backend": response,
                },
                ensure_ascii=False,
            )
        )
        return 0
    except (LLMLabelingError, ValueError, RuntimeError, OSError) as error:
        print(
            json.dumps({"status": "FAILED", "error": str(error)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 1
    finally:
        if connection is not None:
            connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
