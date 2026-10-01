"""Part A consumer-text parser for the V2.2 Backend handoff.

This module deliberately stops at typed demand parsing. It does not finalize
``label`` or ``processed_at`` because those require the selected product's
Facet profile. It also does not create boards, clusters, embeddings, seller
matches, or call an LLM.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pandas as pd

from ..demand_clustering.part_a_integration import build_part_b_parser
from ..demand_constraints import DemandConstraintParser
from .labeling import TaxonomyLoader
from .part_a_input_policy import PartAConstraintInputPolicy

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
    id_column = (
        "id"
        if "id" in frame.columns
        else "catalog_seed_id"
        if "catalog_seed_id" in frame.columns
        else None
    )
    if not id_column:
        return {}
    result: dict[str, str] = {}
    for raw_catalog_id, raw_category_id in frame[
        [id_column, "category_id"]
    ].fillna("").itertuples(index=False, name=None):
        catalog_id = str(raw_catalog_id).strip()
        category_id = str(raw_category_id).strip()
        if not catalog_id or not category_id:
            continue
        previous = result.get(catalog_id)
        if previous is not None and previous != category_id:
            raise ValueError(
                f"catalog ID has conflicting category IDs: {catalog_id}"
            )
        result[catalog_id] = category_id
    return result


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


def run_part_a_batch(
    demands: pd.DataFrame,
    taxonomy_path: Path | None,
    rules_path: Path,
    alias_registry_path: Path | None,
    *,
    taxonomy_payload: Mapping[str, Any] | None = None,
    compatibility_alias_registry_path: Path | None = None,
    skip_processed: bool = True,
    catalog: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Parse a batch and return only Part A's typed contract output."""

    if taxonomy_payload is not None:
        # Production Labeling reads category.facet from Backend and builds the
        # taxonomy in memory. Do not require a local artifact in that mode.
        taxonomy = TaxonomyLoader(dict(taxonomy_payload))
    elif taxonomy_path is not None:
        taxonomy = TaxonomyLoader.from_path(taxonomy_path)
    else:
        raise ValueError("taxonomy_path or taxonomy_payload is required")
    payload = taxonomy.taxonomy
    parser = DemandConstraintParser.from_taxonomy(
        payload,
        rules_path=rules_path,
        aliases_path=alias_registry_path,
        policy_cls=PartAConstraintInputPolicy,
    )
    payload = taxonomy.taxonomy
    if compatibility_alias_registry_path is not None:
        # Keep the Part B integration helper backward-compatible: older B
        # branches do not accept a Part A policy class, so apply the A policy
        # after B has enriched the taxonomy aliases.
        enriched_parser, _ = build_part_b_parser(
            payload,
            rules_path=rules_path,
            aliases_path=alias_registry_path,
            compatibility_aliases_path=compatibility_alias_registry_path,
        )
        parser = DemandConstraintParser(
            extractor=enriched_parser.extractor,
            input_policy=PartAConstraintInputPolicy(
                enriched_parser.input_policy.matcher,
                enriched_parser.extractor,
            ),
        )
    else:
        parser = DemandConstraintParser.from_taxonomy(
            payload,
            rules_path=rules_path,
            aliases_path=alias_registry_path,
            policy_cls=PartAConstraintInputPolicy,
        )
    source = demands.fillna("").copy()
    if skip_processed and "processed_at" in source.columns:
        source = source[source["processed_at"].astype(str).str.strip().eq("")].copy()
    catalog_map = _category_map(catalog) if catalog is not None else None
    rows: list[dict[str, Any]] = []
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
            # Labeling is required for the original-catalog clustering path as
            # well.  ``is_substitutable`` gates B's cross-catalog substitute
            # path; it must not discard the demand's own Facet requirement.
            # Keep the validated consent value in the handoff row, but parse
            # the requirement independently of that routing decision.
            result = parser.interpret(
                category_id,
                requirement,
                is_substitutable=True,
            ).to_dict()
            status = str(result["status"])
            if status not in STATUSES:
                status = "REVIEW"
            constraints = _contract_constraints(taxonomy, category_id, result)
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
                # This stage only interprets consumer text. A final numeric
                # label requires the selected product's complete Facet profile
                # and is created by the labeling runtime after that is joined.
                "label": "",
                "facet_values": "{}",
                "parserVersion": RUNTIME_VERSION,
                # Parsing success is not final Demand labeling completion.
                "processed_at": "",
            })
        except (KeyError, TypeError, ValueError, IndexError) as error:
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
