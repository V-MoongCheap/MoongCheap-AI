from __future__ import annotations

import json

import pandas as pd

from moongcheap_ai.demand_clustering.function_relation_registry import (
    FunctionCoverageRelationRegistry,
)
from moongcheap_ai.demand_clustering.evaluation.product_candidate_graph import (
    add_candidate_demand_coverage,
    build_offline_product_candidate_graph,
)


def _profile(catalog_id: str, category: str, claims: list[str]) -> dict[str, str]:
    return {
        "catalog_id": catalog_id,
        "source_product_id": f"product-{catalog_id}",
        "service_category_id": category,
        "profile_status": "CANDIDATE_READY",
        "main_functionality_claim_ids_json": json.dumps(claims),
    }


def test_builds_identity_and_relation_assisted_offline_pairs() -> None:
    profiles = pd.DataFrame([
        _profile("a", "cat", ["eye"]),
        _profile("b", "cat", ["eye", "antioxidant"]),
        _profile("c", "cat", ["broader-eye"]),
        _profile("d", "other", ["eye"]),
    ])
    registry = FunctionCoverageRelationRegistry(
        artifact_version="test-v1",
        rule_version="v3",
        artifact_fingerprint_sha256="a" * 64,
        edges=frozenset({("eye", "broader-eye")}),
    )

    pairs, sources, summary = build_offline_product_candidate_graph(
        profiles,
        registry,
    )

    pair_modes = {
        (row.source_catalog_id, row.candidate_catalog_id): row.coverage_mode
        for row in pairs.itertuples(index=False)
    }
    assert pair_modes[("a", "b")] == "IDENTITY_ONLY"
    assert pair_modes[("a", "c")] == "RELATION_ASSISTED"
    assert ("b", "a") not in pair_modes
    assert ("c", "a") not in pair_modes
    assert summary["possibleDirectedSameCategoryPairs"] == 6
    assert summary["eligibleDirectedPairs"] == 2
    availability = sources.set_index("source_catalog_id")[
        "candidate_availability"
    ].to_dict()
    assert availability == {
        "a": "HAS_CANDIDATE",
        "b": "NO_CANDIDATE",
        "c": "NO_CANDIDATE",
        "d": "NO_CANDIDATE",
    }


def test_adds_demand_weighted_candidate_coverage() -> None:
    demands = pd.DataFrame([
        {"catalog_id": "a", "is_substitutable": True},
        {"catalog_id": "a", "is_substitutable": False},
        {"catalog_id": "b", "is_substitutable": True},
        {"catalog_id": "missing", "is_substitutable": True},
    ])
    sources = pd.DataFrame([
        {
            "source_catalog_id": "a",
            "candidate_availability": "HAS_CANDIDATE",
            "identity_only_candidate_count": 0,
            "relation_assisted_candidate_count": 1,
        },
        {
            "source_catalog_id": "b",
            "candidate_availability": "NO_CANDIDATE",
            "identity_only_candidate_count": 0,
            "relation_assisted_candidate_count": 0,
        },
    ])

    result = add_candidate_demand_coverage({}, demands, sources)

    assert result["demandCoverage"] == {
        "substitutionConsentedRows": 3,
        "readySourceRows": 2,
        "sourceWithCandidateRows": 1,
        "sourceRescuedByRelationRows": 1,
        "sourceWithCandidateRateAmongConsented": 0.333333,
        "sourceWithCandidateRateAmongReady": 0.5,
    }
