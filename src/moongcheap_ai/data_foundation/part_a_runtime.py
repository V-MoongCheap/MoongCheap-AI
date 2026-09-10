"""Part A Consumer Demand runtime for the V2.2 Backend handoff.

This module deliberately stops at demand parsing.  It does not create boards,
clusters, embeddings, seller matches, or call an LLM.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from ..demand_constraints import DemandConstraintParser
from .labeling import TaxonomyLoader


RUNTIME_VERSION = "part-a-runtime.v2.2"
STATUSES = {
    "PARSED",
    "PASSTHROUGH",
    "NONE",
    "CONFLICT",
    "TAXONOMY_AMBIGUOUS",
    "REVIEW",
    "NOT_APPLICABLE",
}


def _substitution_consent(value: object) -> bool | None:
    """Return consent, or None when the input is outside the contract."""

    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().casefold()
    if normalized in {"1", "1.0", "true", "yes", "y", "동의"}:
        return True
    if normalized in {"0", "0.0", "false", "no", "n", ""}:
        return False
    return None


def _category_map(frame: pd.DataFrame) -> dict[str, str]:
    if "category_id" not in frame.columns:
        return {}
    id_column = "id" if "id" in frame.columns else "catalog_seed_id" if "catalog_seed_id" in frame.columns else None
    if not id_column:
        return {}
    return dict(zip(frame[id_column].astype(str), frame["category_id"].astype(str)))


def _facet_index(loader: TaxonomyLoader, category_id: str) -> dict[str, dict[str, Any]]:
    category = loader.category(category_id)
    if category is None:
        return {}
    return {
        str(facet["name"]): facet
        for facet in category.get("facets", [])
        if isinstance(facet, Mapping) and str(facet.get("name", "")).strip()
    }


def _contract_constraints(loader: TaxonomyLoader, category_id: str, result: Mapping[str, Any]) -> list[dict[str, Any]]:
    facets = _facet_index(loader, category_id)
    constraints: list[dict[str, Any]] = []
    for item in result.get("constraints", []):
        facet_key = str(item.get("facet_name", ""))
        facet = facets.get(facet_key, {})
        constraints.append({
            "facetKey": facet_key,
            "canonicalValue": str(item.get("value", "")),
            "facetCode": int(facet.get("facet_id", 0) or 0),
            "valueCode": int(item.get("value_code", 0) or 0),
            "constraintType": str(item.get("constraint_type", "PREFER")),
            "evidence": str(item.get("evidence_clause", "")),
        })
    return constraints


def _label(loader: TaxonomyLoader, category_id: str, constraints: list[dict[str, Any]]) -> tuple[str, dict[str, dict[str, Any]]]:
    facets = _facet_index(loader, category_id)
    values: dict[str, dict[str, Any]] = {}
    for name, facet in facets.items():
        all_value = next((item for item in facet.get("values", []) if int(item.get("code", -1)) == 0), {"value": "ALL"})
        values[name] = {"code": 0, "value": all_value.get("value", "ALL")}
    for item in constraints:
        # A single label cannot represent ANY_OF or repeated values reliably.
        # Keep ALL in that case and leave the typed constraints to downstream code.
        if item["facetKey"] in values and item["constraintType"] in {"MUST", "EXCLUDE"}:
            values[item["facetKey"]] = {"code": item["valueCode"], "value": item["canonicalValue"]}
    ordered = sorted(facets.items(), key=lambda pair: int(pair[1].get("order", 0)))
    return "-".join(str(values[name]["code"]) for name, _ in ordered), values


def run_part_a_batch(
    demands: pd.DataFrame,
    taxonomy_path: Path,
    rules_path: Path,
    alias_registry_path: Path,
    *,
    processed_at: str | None = None,
    skip_processed: bool = True,
    catalog: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Parse a batch and return only Part A's typed contract output."""

    taxonomy = TaxonomyLoader.from_path(taxonomy_path)
    payload = taxonomy.taxonomy
    parser = DemandConstraintParser.from_taxonomy(
        payload, rules_path=rules_path, aliases_path=alias_registry_path
    )
    source = demands.fillna("").copy()
    if skip_processed and "processed_at" in source.columns:
        source = source[source["processed_at"].astype(str).str.strip().eq("")].copy()
    catalog_map = _category_map(catalog) if catalog is not None else None
    rows: list[dict[str, Any]] = []
    now = processed_at or datetime.now(timezone.utc).isoformat()
    for raw in source.to_dict(orient="records"):
        row = dict(raw)
        try:
            category_id = str(raw.get("category_id") or raw.get("kan_code") or "")
            if not category_id and catalog_map:
                category_id = catalog_map.get(str(raw.get("catalog_id", "")), "")
            # A parser result is only meaningful in a known category.  In
            # particular, TaxonomyLoader supports a root fallback for legacy
            # reads; the batch runtime must not use that fallback for demand
            # labeling because it can turn an unknown category into a valid
            # looking PASSTHROUGH result.
            category_reason = ""
            if not category_id:
                category_reason = "CATEGORY_MISSING"
            elif category_id not in taxonomy.categories:
                category_reason = "CATEGORY_NOT_IN_TAXONOMY"
            if category_reason:
                row.update({
                    "category_id": category_id,
                    "demandId": raw.get("demand_id", ""),
                    "catalogId": raw.get("catalog_id", ""),
                    "categoryId": category_id,
                    "taxonomyVersion": str(payload.get("version", "v2.2")),
                    "status": "REVIEW",
                    "effectiveRequirementMode": "NONE",
                    "constraints": "[]",
                    "warnings": "[]",
                    "clauses": "[]",
                    "interpretation_method": "CATEGORY_PREVALIDATION",
                    "preferenceGroups": "[]",
                    "passthroughText": None,
                    "semantic_preferences": "[]",
                    "diagnostic_code": category_reason,
                    "taxonomy_equivalences": "[]",
                    "reasonCodes": json.dumps([category_reason], ensure_ascii=False),
                    "label": "",
                    "facet_values": "{}",
                    "parserVersion": RUNTIME_VERSION,
                    # The demand was not parsed, so it must remain eligible
                    # for a later retry after category data is repaired.
                    "processed_at": "",
                })
                rows.append(row)
                continue
            has_substitution_consent = "is_substitutable" in source.columns
            is_substitutable = (
                _substitution_consent(raw.get("is_substitutable"))
                if has_substitution_consent
                else True
            )
            if is_substitutable is None:
                row.update({
                    "category_id": category_id,
                    "demandId": raw.get("demand_id", ""),
                    "catalogId": raw.get("catalog_id", ""),
                    "categoryId": category_id,
                    "taxonomyVersion": str(payload.get("version", "v2.2")),
                    "status": "REVIEW",
                    "effectiveRequirementMode": "NONE",
                    "constraints": "[]",
                    "warnings": "[]",
                    "clauses": "[]",
                    "interpretation_method": "INPUT_PREVALIDATION",
                    "preferenceGroups": "[]",
                    "passthroughText": None,
                    "semantic_preferences": "[]",
                    "diagnostic_code": "INVALID_IS_SUBSTITUTABLE",
                    "taxonomy_equivalences": "[]",
                    "reasonCodes": json.dumps(["INVALID_IS_SUBSTITUTABLE"], ensure_ascii=False),
                    "label": "",
                    "facet_values": "{}",
                    "parserVersion": RUNTIME_VERSION,
                    "processed_at": "",
                })
                rows.append(row)
                continue
            requirement = str(raw.get("extra_requirement", "") or "").strip()
            result = parser.interpret(
                category_id,
                requirement,
                is_substitutable=is_substitutable,
            ).to_dict()
            status = str(result["status"])
            if status not in STATUSES:
                status = "REVIEW"
            constraints = _contract_constraints(taxonomy, category_id, result)
            label, facet_values = _label(taxonomy, category_id, constraints)
            reason_codes = list(result.get("warnings", []))
            if result.get("diagnostic_code"):
                reason_codes.insert(0, str(result["diagnostic_code"]))
            if result.get("interpretation_method"):
                reason_codes.append(str(result["interpretation_method"]))
            row.update({
                "category_id": category_id,
                "demandId": raw.get("demand_id", ""),
                "catalogId": raw.get("catalog_id", ""),
                "categoryId": category_id,
                "taxonomyVersion": str(payload.get("version", "v2.2")),
                "status": status,
                "effectiveRequirementMode": str(result["effective_requirement_mode"]),
                "constraints": json.dumps(constraints, ensure_ascii=False, separators=(",", ":")),
                "preferenceGroups": json.dumps(result.get("preference_groups", []), ensure_ascii=False, separators=(",", ":")),
                "passthroughText": requirement if status == "PASSTHROUGH" else None,
                "reasonCodes": json.dumps(reason_codes, ensure_ascii=False, separators=(",", ":")),
                "label": label,
                "facet_values": json.dumps(facet_values, ensure_ascii=False, separators=(",", ":")),
                "parserVersion": RUNTIME_VERSION,
                "processed_at": now,
            })
        except Exception as error:  # isolate one malformed demand from the batch
            row.update({
                "taxonomyVersion": str(payload.get("version", "v2.2")),
                "status": "REVIEW",
                "effectiveRequirementMode": "NONE",
                "constraints": "[]",
                "preferenceGroups": "[]",
                "passthroughText": None,
                "reasonCodes": json.dumps(["PARSER_EXCEPTION"], ensure_ascii=False),
                "label": "",
                "facet_values": "{}",
                "parserVersion": RUNTIME_VERSION,
                "processed_at": "",
                "errorType": type(error).__name__,
            })
        rows.append(row)
    output = pd.DataFrame(rows)
    counts = output["status"].value_counts().to_dict() if not output.empty else {}
    summary = {
        "status": "COMPLETED",
        "runtimeVersion": RUNTIME_VERSION,
        "taxonomyVersion": str(payload.get("version", "v2.2")),
        "rows": len(output),
        "statusCounts": {key: int(counts.get(key, 0)) for key in sorted(STATUSES)},
        "externalLlmCalls": 0,
        "parserExceptionCount": int(sum(row.get("reasonCodes") == '["PARSER_EXCEPTION"]' for row in rows)),
        "categoryPrevalidationFailureCount": int(sum(
            row.get("diagnostic_code") in {"CATEGORY_MISSING", "CATEGORY_NOT_IN_TAXONOMY"}
            for row in rows
        )),
        "clustering": "NOT_PERFORMED",
        "sellerMatching": "NOT_PERFORMED",
    }
    return output, summary
