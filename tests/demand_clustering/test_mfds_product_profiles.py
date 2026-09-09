from __future__ import annotations

import pandas as pd

from moongcheap_ai.demand_clustering.evaluation.function_claims import function_claim_key
from moongcheap_ai.demand_clustering.evaluation.mfds_product_profiles import (
    add_demand_profile_coverage,
    build_catalog_wide_mappings,
    build_mfds_product_profile_candidates,
)


CLAIM_TEXT = "면역력 증진에 도움을 줄 수 있음"


def test_builds_catalog_wide_mappings_without_demand_rows() -> None:
    category_mappings = pd.DataFrame([
        {
            "source_product_id": "mfds-1",
            "service_category_candidate_key": "RED_GINSENG",
        },
        {
            "source_product_id": "mfds-2",
            "service_category_candidate_key": (
                "health-functional-food:probiotics"
            ),
        },
        {
            "source_product_id": "mfds-3",
            "service_category_candidate_key": "UNMAPPED",
        },
    ])

    mappings, summary = build_catalog_wide_mappings(
        category_mappings,
        taxonomy_version="v2.1",
    )

    assert mappings.to_dict("records") == [
        {
            "catalog_id": "mfds-1",
            "product_reference": "mfds-1",
            "service_category_key": (
                "health-functional-food:red_ginseng"
            ),
            "taxonomy_version": "v2.1",
        },
        {
            "catalog_id": "mfds-2",
            "product_reference": "mfds-2",
            "service_category_key": (
                "health-functional-food:probiotics"
            ),
            "taxonomy_version": "v2.1",
        },
    ]
    assert summary == {
        "sourceRows": 3,
        "includedCatalogMappings": 2,
        "excludedUnmappedRows": 1,
    }


def test_product_name_does_not_decide_catalog_eligibility() -> None:
    catalogs = pd.DataFrame([
        {
            "catalog_id": "catalog-1",
            "product_reference": "p1",
            "service_category_key": "health-functional-food:red_ginseng",
            "taxonomy_version": "v2.1",
        },
        {
            "catalog_id": "catalog-2",
            "product_reference": "p2",
            "service_category_key": "health-functional-food:red_ginseng",
            "taxonomy_version": "v2.1",
        },
    ])
    products = pd.DataFrame([
        {
            "source_product_id": "p1",
            "name": "홍삼 완제품",
            "product_type": "홍삼",
            "product_form": "액상",
            "main_functionality": CLAIM_TEXT,
            "intake_method": "1일 1회 섭취",
            "functional_ingredients": "홍삼",
        },
        {
            "source_product_id": "p2",
            "name": "홍삼 완제품(전량수출용)",
            "product_type": "홍삼",
            "product_form": "액상",
            "main_functionality": CLAIM_TEXT,
            "intake_method": "1일 1회 섭취",
            "functional_ingredients": "홍삼",
        },
    ])
    references = pd.DataFrame([{
        "category_reference_name": "홍삼",
        "main_functionality": "① " + CLAIM_TEXT,
        "ingredient_name": "진세노사이드",
    }])
    claims = pd.DataFrame([{
        "claim_key_candidate": function_claim_key(CLAIM_TEXT),
        "claim_text_candidate": CLAIM_TEXT,
    }])

    profiles, summary = build_mfds_product_profile_candidates(
        catalogs,
        products,
        references,
        claims,
    )

    by_id = profiles.set_index("catalog_id")
    assert by_id.at["catalog-1", "profile_status"] == "EVIDENCE_READY"
    assert by_id.at["catalog-1", "record_type"] == "FINISHED_PRODUCT"
    assert by_id.at[
        "catalog-1", "main_functionality_claim_ids_json"
    ].startswith('["MFDS-FCLAIM-')
    assert by_id.at["catalog-2", "profile_status"] == "EVIDENCE_READY"
    assert by_id.at["catalog-2", "profile_reason_codes"] == ""
    assert summary["exactI0030Join"] == 2
    assert summary["evidenceReadyRate"] == 1.0
    assert "Catalog eligibility is an upstream input" in summary[
        "responsibilityBoundary"
    ]


def test_adds_row_weighted_substitution_coverage() -> None:
    demands = pd.DataFrame([
        {"catalog_id": "a", "is_substitutable": "true"},
        {"catalog_id": "a", "is_substitutable": "false"},
        {"catalog_id": "b", "is_substitutable": "true"},
    ])
    profiles = pd.DataFrame([
        {"catalog_id": "a", "profile_status": "EVIDENCE_READY"},
        {"catalog_id": "b", "profile_status": "INSUFFICIENT_EVIDENCE"},
    ])

    result = add_demand_profile_coverage({}, demands, profiles)

    assert result["demandCoverage"] == {
        "rows": 3,
        "evidenceReadyRows": 2,
        "evidenceReadyRate": 0.666667,
        "substitutionConsentedRows": 2,
        "substitutionConsentedEvidenceReadyRows": 1,
        "substitutionConsentedEvidenceReadyRate": 0.5,
    }
