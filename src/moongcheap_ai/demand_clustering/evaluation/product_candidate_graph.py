"""Build an exhaustive offline catalog graph behind the relation hard gate."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any

import pandas as pd

from ..function_relation_registry import FunctionCoverageRelationRegistry
from ..profile_contract import SUBSTITUTION_EVIDENCE_READY_STATUSES


PROFILE_COLUMNS = {
    "catalog_id",
    "source_product_id",
    "service_category_id",
    "profile_status",
    "main_functionality_claim_ids_json",
}


def _pair_id(source_catalog_id: str, candidate_catalog_id: str) -> str:
    key = f"{source_catalog_id}->{candidate_catalog_id}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16].upper()
    return f"CATALOG-PAIR-{digest}"


def _claim_ids(value: object) -> tuple[str, ...]:
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError as error:
        raise ValueError("function claim IDs must be a JSON array") from error
    if not isinstance(parsed, list):
        raise ValueError("function claim IDs must be a JSON array")
    normalized = tuple(sorted({str(item).strip() for item in parsed}))
    if not normalized or any(not item for item in normalized):
        raise ValueError("candidate-ready profiles require nonblank claim IDs")
    return normalized


def build_offline_product_candidate_graph(
    profiles: pd.DataFrame,
    registry: FunctionCoverageRelationRegistry,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Enumerate same-category pairs to diagnose the hard-gate candidate pool.

    This exhaustive graph is an evaluation oracle for the small grounded set,
    not the production retrieval algorithm.
    """

    if missing := sorted(PROFILE_COLUMNS - set(profiles.columns)):
        raise ValueError("profiles missing columns: " + ", ".join(missing))
    normalized = profiles.fillna("").copy()
    if normalized["catalog_id"].duplicated().any():
        raise ValueError("profile catalog IDs must be unique")
    ready = normalized.loc[
        normalized["profile_status"].isin(
            SUBSTITUTION_EVIDENCE_READY_STATUSES
        )
    ].copy()
    ready["claim_ids"] = ready["main_functionality_claim_ids_json"].map(
        _claim_ids
    )

    pair_rows = []
    possible_pairs = 0
    for category, group in ready.groupby("service_category_id", sort=True):
        records = group.sort_values("catalog_id").to_dict("records")
        possible_pairs += len(records) * max(0, len(records) - 1)
        for source in records:
            for candidate in records:
                if source["catalog_id"] == candidate["catalog_id"]:
                    continue
                resolution = registry.resolve(
                    tuple(source["claim_ids"]),
                    tuple(candidate["claim_ids"]),
                )
                if not resolution.fully_covered:
                    continue
                relation_assisted = any(
                    source_claim != candidate_claim
                    for source_claim, candidate_claim in resolution.covered_by
                )
                pair_rows.append({
                    "pair_id": _pair_id(
                        str(source["catalog_id"]),
                        str(candidate["catalog_id"]),
                    ),
                    "source_catalog_id": source["catalog_id"],
                    "candidate_catalog_id": candidate["catalog_id"],
                    "source_product_id": source["source_product_id"],
                    "candidate_product_id": candidate["source_product_id"],
                    "service_category_id": category,
                    "source_claim_ids_json": json.dumps(
                        source["claim_ids"],
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    "candidate_claim_ids_json": json.dumps(
                        candidate["claim_ids"],
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    "coverage_witnesses_json": json.dumps(
                        resolution.covered_by,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    "coverage_mode": (
                        "RELATION_ASSISTED"
                        if relation_assisted
                        else "IDENTITY_ONLY"
                    ),
                    "relation_artifact_version": registry.artifact_version,
                    "relation_artifact_fingerprint_sha256": (
                        registry.artifact_fingerprint_sha256
                    ),
                })

    columns = [
        "pair_id",
        "source_catalog_id",
        "candidate_catalog_id",
        "source_product_id",
        "candidate_product_id",
        "service_category_id",
        "source_claim_ids_json",
        "candidate_claim_ids_json",
        "coverage_witnesses_json",
        "coverage_mode",
        "relation_artifact_version",
        "relation_artifact_fingerprint_sha256",
    ]
    pairs = pd.DataFrame(pair_rows, columns=columns).sort_values(
        "pair_id",
        kind="stable",
    ).reset_index(drop=True)

    counts_by_source = Counter(pairs["source_catalog_id"])
    identity_counts = Counter(
        pairs.loc[
            pairs["coverage_mode"].eq("IDENTITY_ONLY"),
            "source_catalog_id",
        ]
    )
    relation_counts = Counter(
        pairs.loc[
            pairs["coverage_mode"].eq("RELATION_ASSISTED"),
            "source_catalog_id",
        ]
    )
    source_rows = []
    for row in ready.sort_values("catalog_id").itertuples(index=False):
        source_rows.append({
            "source_catalog_id": row.catalog_id,
            "source_product_id": row.source_product_id,
            "service_category_id": row.service_category_id,
            "eligible_candidate_count": counts_by_source[row.catalog_id],
            "identity_only_candidate_count": identity_counts[row.catalog_id],
            "relation_assisted_candidate_count": relation_counts[row.catalog_id],
            "candidate_availability": (
                "HAS_CANDIDATE"
                if counts_by_source[row.catalog_id]
                else "NO_CANDIDATE"
            ),
        })
    sources = pd.DataFrame(source_rows)
    counts = sources["eligible_candidate_count"]
    positive_counts = counts.loc[counts.gt(0)]
    coverage_modes = {
        mode: int(pairs["coverage_mode"].eq(mode).sum())
        for mode in ("IDENTITY_ONLY", "RELATION_ASSISTED")
    }
    summary = {
        "schemaVersion": "offline-product-candidate-graph.v1",
        "evaluationMode": "EXHAUSTIVE_SAME_CATEGORY_DIAGNOSTIC",
        "readyProfiles": len(ready),
        "possibleDirectedSameCategoryPairs": possible_pairs,
        "eligibleDirectedPairs": len(pairs),
        "coverageModeCounts": coverage_modes,
        "sourcesWithCandidate": int(counts.gt(0).sum()),
        "sourcesWithoutCandidate": int(counts.eq(0).sum()),
        "sourcesWithRelationAssistedCandidate": int(
            sources["relation_assisted_candidate_count"].gt(0).sum()
        ),
        "sourcesRescuedByRelation": int((
            sources["identity_only_candidate_count"].eq(0)
            & sources["relation_assisted_candidate_count"].gt(0)
        ).sum()),
        "candidateCountForCoveredSources": {
            "min": int(positive_counts.min()) if len(positive_counts) else 0,
            "median": float(positive_counts.median()) if len(positive_counts) else 0,
            "mean": round(float(positive_counts.mean()), 6)
            if len(positive_counts)
            else 0,
            "p90": float(positive_counts.quantile(0.9))
            if len(positive_counts)
            else 0,
            "max": int(positive_counts.max()) if len(positive_counts) else 0,
        },
        "relationArtifactVersion": registry.artifact_version,
        "relationArtifactFingerprintSha256": (
            registry.artifact_fingerprint_sha256
        ),
        "runtimePolicy": (
            "This graph is an offline diagnostic. Production must retrieve a "
            "bounded CPU-ranked pool and load only an APPROVED relation artifact."
        ),
    }
    return pairs, sources, summary


def add_candidate_demand_coverage(
    summary: dict[str, Any],
    demands: pd.DataFrame,
    sources: pd.DataFrame,
) -> dict[str, Any]:
    """Add demand-weighted catalog-candidate availability to the summary."""

    required = {"catalog_id", "is_substitutable"}
    if missing := sorted(required - set(demands.columns)):
        raise ValueError("demands missing columns: " + ", ".join(missing))
    availability = set(
        sources.loc[
            sources["candidate_availability"].eq("HAS_CANDIDATE"),
            "source_catalog_id",
        ].astype(str)
    )
    relation_rescued = set(
        sources.loc[
            sources["identity_only_candidate_count"].eq(0)
            & sources["relation_assisted_candidate_count"].gt(0),
            "source_catalog_id",
        ].astype(str)
    )
    ready = set(sources["source_catalog_id"].astype(str))
    frame = demands.fillna("").copy()
    consented = frame["is_substitutable"].astype(str).str.casefold().eq("true")
    ready_source = frame["catalog_id"].astype(str).isin(ready)
    has_candidate = frame["catalog_id"].astype(str).isin(availability)
    rescued_by_relation = frame["catalog_id"].astype(str).isin(
        relation_rescued
    )
    return {
        **summary,
        "demandCoverage": {
            "substitutionConsentedRows": int(consented.sum()),
            "readySourceRows": int((consented & ready_source).sum()),
            "sourceWithCandidateRows": int((consented & has_candidate).sum()),
            "sourceRescuedByRelationRows": int(
                (consented & rescued_by_relation).sum()
            ),
            "sourceWithCandidateRateAmongConsented": round(
                float((consented & has_candidate).sum() / consented.sum()),
                6,
            ) if consented.any() else 0.0,
            "sourceWithCandidateRateAmongReady": round(
                float(
                    (consented & has_candidate).sum()
                    / (consented & ready_source).sum()
                ),
                6,
            ) if (consented & ready_source).any() else 0.0,
        },
    }
