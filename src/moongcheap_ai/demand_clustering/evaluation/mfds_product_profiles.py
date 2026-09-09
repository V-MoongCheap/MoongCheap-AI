"""Build auditable MFDS-backed catalog profiles for substitution evaluation."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any

import pandas as pd

from ...data_foundation.health_v1 import classify_record_type, split_ingredient_text
from .evidence_analysis import (
    _ReferenceIndex,
    _structural_status,
    _text,
)
from .function_claims import extract_atomic_function_claims, function_claim_key
from .function_relation_review import function_claim_id
from ..profile_contract import SUBSTITUTION_EVIDENCE_READY_STATUSES


CATALOG_COLUMNS = {
    "catalog_id",
    "product_reference",
    "service_category_key",
    "taxonomy_version",
}
PRODUCT_COLUMNS = {
    "source_product_id",
    "name",
    "product_type",
    "product_form",
    "main_functionality",
    "intake_method",
    "functional_ingredients",
}
REFERENCE_COLUMNS = {
    "category_reference_name",
    "main_functionality",
    "ingredient_name",
}
CLAIM_COLUMNS = {"claim_key_candidate", "claim_text_candidate"}
PART_A_CATEGORY_MAPPING_COLUMNS = {
    "source_product_id",
    "service_category_candidate_key",
}


def _json_array(values: list[str] | tuple[str, ...]) -> str:
    return json.dumps(values, ensure_ascii=False, separators=(",", ":"))


def _validate_catalog_mappings(catalogs: pd.DataFrame) -> pd.DataFrame:
    if missing := sorted(CATALOG_COLUMNS - set(catalogs.columns)):
        raise ValueError("catalog mappings missing columns: " + ", ".join(missing))
    mappings = (
        catalogs.fillna("")
        .loc[:, sorted(CATALOG_COLUMNS)]
        .astype(str)
        .drop_duplicates()
    )
    if mappings[list(CATALOG_COLUMNS)].eq("").any().any():
        raise ValueError("catalog mapping values must not be blank")
    for column in (
        "product_reference",
        "service_category_key",
        "taxonomy_version",
    ):
        if mappings.groupby("catalog_id")[column].nunique().gt(1).any():
            raise ValueError(f"one catalog_id maps to multiple {column} values")
    return mappings.drop_duplicates("catalog_id").sort_values("catalog_id")


def build_catalog_wide_mappings(
    category_mappings: pd.DataFrame,
    *,
    taxonomy_version: str,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Adapt the Part A MFDS category mapping to the profile input contract.

    Catalog-wide MFDS evidence is keyed by ``source_product_id``.  A separate
    binding can later translate that stable source identifier to the Backend
    ``product_catalog.id`` without rebuilding the evidence itself.
    """

    if missing := sorted(
        PART_A_CATEGORY_MAPPING_COLUMNS - set(category_mappings.columns)
    ):
        raise ValueError(
            "Part A category mappings missing columns: " + ", ".join(missing)
        )
    resolved_taxonomy_version = str(taxonomy_version).strip()
    if not resolved_taxonomy_version:
        raise ValueError("taxonomy_version must not be blank")

    mappings = category_mappings.fillna("").copy()
    mappings["source_product_id"] = mappings["source_product_id"].astype(
        str
    ).str.strip()
    mappings["service_category_candidate_key"] = mappings[
        "service_category_candidate_key"
    ].astype(str).str.strip()
    if mappings["source_product_id"].eq("").any():
        raise ValueError("Part A source_product_id values must not be blank")
    if mappings["source_product_id"].duplicated().any():
        raise ValueError("Part A source_product_id values must be unique")

    unmapped = mappings["service_category_candidate_key"].str.upper().isin(
        {"", "UNMAPPED"}
    )
    included = mappings.loc[~unmapped].copy()

    def service_category_id(value: str) -> str:
        normalized = value.strip().casefold()
        if normalized.startswith("health-functional-food:"):
            return normalized
        return "health-functional-food:" + normalized

    result = pd.DataFrame({
        # This is an MFDS evidence identifier, not the Backend DB PK.
        "catalog_id": included["source_product_id"],
        "product_reference": included["source_product_id"],
        "service_category_key": included[
            "service_category_candidate_key"
        ].map(service_category_id),
        "taxonomy_version": resolved_taxonomy_version,
    }).sort_values("catalog_id", kind="stable").reset_index(drop=True)
    return result, {
        "sourceRows": int(len(mappings)),
        "includedCatalogMappings": int(len(result)),
        "excludedUnmappedRows": int(unmapped.sum()),
    }


def _record_type(record_type_candidate: str) -> str:
    return {
        "FINISHED_PRODUCT_CANDIDATE": "FINISHED_PRODUCT",
        "INGREDIENT_MATERIAL_CANDIDATE": "INGREDIENT_MATERIAL",
    }.get(record_type_candidate, "UNKNOWN")


def _fingerprint(frame: pd.DataFrame) -> str:
    columns = [
        "catalog_id",
        "source_product_id",
        "service_category_id",
        "taxonomy_version",
        "profile_status",
        "main_functionality_claim_ids_json",
    ]
    canonical = frame.loc[:, columns].fillna("").astype(str).sort_values(columns)
    payload = "\n".join(
        "\x1f".join(row)
        for row in canonical.itertuples(index=False, name=None)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_mfds_product_profile_candidates(
    catalogs: pd.DataFrame,
    products: pd.DataFrame,
    references: pd.DataFrame,
    claim_candidates: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Create one evidence profile per catalog mapping and coverage metrics.

    `EVIDENCE_READY` means only that function evidence can be reconstructed.
    Catalog eligibility belongs to the upstream catalog owner and is not
    inferred here from MFDS names or record types.
    """

    mappings = _validate_catalog_mappings(catalogs)
    if missing := sorted(PRODUCT_COLUMNS - set(products.columns)):
        raise ValueError("I0030 products missing columns: " + ", ".join(missing))
    if missing := sorted(REFERENCE_COLUMNS - set(references.columns)):
        raise ValueError("I2710 references missing columns: " + ", ".join(missing))
    if missing := sorted(CLAIM_COLUMNS - set(claim_candidates.columns)):
        raise ValueError("claim candidates missing columns: " + ", ".join(missing))

    product_frame = products.fillna("").copy()
    product_frame["source_product_id"] = product_frame[
        "source_product_id"
    ].astype(str)
    if product_frame["source_product_id"].duplicated().any():
        raise ValueError("I0030 source_product_id values must be unique")
    products_by_id = product_frame.set_index("source_product_id", drop=False)
    reference_index = _ReferenceIndex(references.fillna(""))
    claims = claim_candidates.fillna("").astype(str)
    if claims["claim_key_candidate"].eq("").any():
        raise ValueError("claim keys must not be blank")
    claim_text_by_key = {
        claim_key: sorted(
            set(group["claim_text_candidate"]),
            key=lambda value: (len(value), value),
        )[0]
        for claim_key, group in claims.groupby(
            "claim_key_candidate",
            sort=True,
        )
    }

    rows = []
    for mapping in mappings.itertuples(index=False):
        catalog_id = str(mapping.catalog_id)
        product_reference = str(mapping.product_reference)
        if product_reference not in products_by_id.index:
            rows.append({
                "catalog_id": catalog_id,
                "source_product_id": product_reference,
                "product_name": "",
                "service_category_id": str(mapping.service_category_key),
                "taxonomy_version": str(mapping.taxonomy_version),
                "record_type": "UNKNOWN",
                "product_form": "",
                "functional_ingredients_json": "[]",
                "main_functionality_claim_ids_json": "[]",
                "main_functionality_claim_texts_json": "[]",
                "reconstructed_i2710_functions_json": "[]",
                "main_functionality_text": "",
                "intake_method_text": "",
                "profile_status": "INSUFFICIENT_EVIDENCE",
                "profile_reason_codes": "I0030_PRODUCT_NOT_FOUND",
            })
            continue

        product = products_by_id.loc[product_reference]
        record_type_candidate = classify_record_type(product)[0]
        ingredients, ingredient_parse_status = split_ingredient_text(
            product["functional_ingredients"]
        )
        resolutions = [reference_index.resolve(value) for value in ingredients]
        structural_status = _structural_status(product, resolutions)
        functions = sorted({
            function
            for resolution in resolutions
            for function in resolution.evidence.functions
            if _text(function)
        })
        extracted_claims = [
            claim
            for function in functions
            for claim in extract_atomic_function_claims(function).claims
        ]
        claim_keys = sorted({
            function_claim_key(claim) for claim in extracted_claims
        })
        unknown_claim_keys = sorted(
            key for key in claim_keys if key not in claim_text_by_key
        )
        claim_ids = [
            function_claim_id(key)
            for key in claim_keys
            if key in claim_text_by_key
        ]
        claim_texts = [
            claim_text_by_key[key]
            for key in claim_keys
            if key in claim_text_by_key
        ]

        reason_codes = []
        if structural_status != "STRUCTURED_RECONSTRUCTION_READY":
            profile_status = "INSUFFICIENT_EVIDENCE"
            reason_codes.append(structural_status)
        elif ingredient_parse_status != "PARSED":
            profile_status = "INSUFFICIENT_EVIDENCE"
            reason_codes.append(
                f"INGREDIENT_PARSE_{ingredient_parse_status}"
            )
        elif not claim_ids:
            profile_status = "INSUFFICIENT_EVIDENCE"
            reason_codes.append("FUNCTION_CLAIMS_MISSING")
        elif unknown_claim_keys:
            profile_status = "INSUFFICIENT_EVIDENCE"
            reason_codes.append("FUNCTION_CLAIM_NOT_IN_RELATION_UNIVERSE")
        else:
            profile_status = "EVIDENCE_READY"

        rows.append({
            "catalog_id": catalog_id,
            "source_product_id": product_reference,
            "product_name": _text(product["name"]),
            "service_category_id": str(mapping.service_category_key),
            "taxonomy_version": str(mapping.taxonomy_version),
            "record_type": _record_type(record_type_candidate),
            "product_form": _text(product["product_form"]),
            "functional_ingredients_json": _json_array(ingredients),
            "main_functionality_claim_ids_json": _json_array(claim_ids),
            "main_functionality_claim_texts_json": _json_array(claim_texts),
            "reconstructed_i2710_functions_json": _json_array(functions),
            "main_functionality_text": _text(product["main_functionality"]),
            "intake_method_text": _text(product["intake_method"]),
            "profile_status": profile_status,
            "profile_reason_codes": "|".join(reason_codes),
        })

    profiles = pd.DataFrame(rows).sort_values("catalog_id").reset_index(drop=True)
    status_counts = {
        str(key): int(value)
        for key, value in profiles["profile_status"].value_counts().items()
    }
    reason_counts: Counter[str] = Counter()
    for value in profiles["profile_reason_codes"]:
        reason_counts.update(code for code in str(value).split("|") if code)
    category_counts = {
        category: {
            str(key): int(value)
            for key, value in group["profile_status"].value_counts().items()
        }
        for category, group in profiles.groupby("service_category_id", sort=True)
    }
    summary = {
        "schemaVersion": "mfds-substitution-function-evidence.v2",
        "catalogMappings": len(mappings),
        "uniqueProductReferences": int(mappings["product_reference"].nunique()),
        "exactI0030Join": int(
            mappings["product_reference"].isin(products_by_id.index).sum()
        ),
        "profileStatusCounts": status_counts,
        "profileReasonCounts": dict(sorted(reason_counts.items())),
        "evidenceReadyRate": round(
            float(profiles["profile_status"].eq("EVIDENCE_READY").mean()),
            6,
        ),
        "categoryProfileStatusCounts": category_counts,
        "profileFingerprintSha256": _fingerprint(profiles),
        "responsibilityBoundary": (
            "EVIDENCE_READY means deterministic function-evidence reconstruction "
            "succeeded. Catalog eligibility is an upstream input and is not "
            "inferred from product names, export markers, or record types."
        ),
    }
    return profiles, summary


def add_demand_profile_coverage(
    summary: dict[str, Any],
    demands: pd.DataFrame,
    profiles: pd.DataFrame,
) -> dict[str, Any]:
    """Add row-weighted overall and substitution-consented coverage metrics."""

    required = {"catalog_id", "is_substitutable"}
    if missing := sorted(required - set(demands.columns)):
        raise ValueError("demands missing columns: " + ", ".join(missing))
    joined = demands.fillna("").merge(
        profiles[["catalog_id", "profile_status"]],
        on="catalog_id",
        how="left",
        validate="many_to_one",
    )
    substitutable = joined["is_substitutable"].astype(str).str.casefold().eq("true")
    ready = joined["profile_status"].isin(
        SUBSTITUTION_EVIDENCE_READY_STATUSES
    )
    return {
        **summary,
        "demandCoverage": {
            "rows": len(joined),
            "evidenceReadyRows": int(ready.sum()),
            "evidenceReadyRate": round(float(ready.mean()), 6),
            "substitutionConsentedRows": int(substitutable.sum()),
            "substitutionConsentedEvidenceReadyRows": int(
                (substitutable & ready).sum()
            ),
            "substitutionConsentedEvidenceReadyRate": round(
                float(ready.loc[substitutable].mean()),
                6,
            ) if substitutable.any() else 0.0,
        },
    }
