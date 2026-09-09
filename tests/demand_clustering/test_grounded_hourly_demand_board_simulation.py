from __future__ import annotations

from datetime import timedelta

import pandas as pd

from scripts.demand.simulate_grounded_hourly_demand_board_handoff import (
    DATA_CLASSIFICATION,
    PROFILE_ORIGIN,
    build_part_c_grounded_hourly_snapshot,
    simulate_grounded_hourly_demand_board_handoff,
)

from .test_demand_board_simulation import TAXONOMY, row
from .test_hourly_demand_board_simulation import (
    START_AT,
    source_id_for_band_and_arrival_half,
)


def profile(product_id: int, name: str) -> dict[str, str]:
    return {
        "catalog_id": f"catalog-seed-{product_id}",
        "source_product_id": str(product_id),
        "product_name": name,
        "service_category_id": "health-functional-food:test",
        "taxonomy_version": "v2.1",
        "record_type": "FINISHED_PRODUCT",
        "product_form": "정",
        "functional_ingredients_json": '["단백질"]',
        "main_functionality_claim_ids_json": '["FUNCTION-1"]',
        "main_functionality_claim_texts_json": '["시험 기능"]',
        "reconstructed_i2710_functions_json": '["시험 기능"]',
        "main_functionality_text": "시험 기능",
        "intake_method_text": "1일 1회 물과 함께 섭취",
        "profile_status": "EVIDENCE_READY",
        "profile_reason_codes": "",
    }


def test_grounded_identity_gate_builds_part_c_snapshot_without_relation() -> None:
    direct_a = row(
        source_id_for_band_and_arrival_half(0, late=False),
        201,
    )
    direct_b = row(
        source_id_for_band_and_arrival_half(0, late=False, offset=1),
        201,
    )
    substitute = row(
        source_id_for_band_and_arrival_half(6, late=True),
        100,
    )
    profiles = pd.DataFrame((profile(100, "원상품"), profile(201, "후보상품")))
    top_candidates = pd.DataFrame((
        {
            "source_catalog_id": "catalog-seed-100",
            "candidate_catalog_id": "catalog-seed-201",
            "rank": 1,
            "hard_gate_eligible": True,
            "coverage_mode": "IDENTITY_ONLY",
        },
        {
            "source_catalog_id": "catalog-seed-201",
            "candidate_catalog_id": "catalog-seed-100",
            "rank": 1,
            "hard_gate_eligible": True,
            "coverage_mode": "RELATION_ASSISTED",
        },
    ))

    output = simulate_grounded_hourly_demand_board_handoff(
        (direct_a, direct_b, substitute),
        TAXONOMY,
        profiles,
        top_candidates,
        start_at=START_AT,
        arrival_window=timedelta(hours=2),
        batch_interval=timedelta(hours=1),
        min_participants=2,
        text_similarity_scorer=None,
    )

    assert output["dataClassification"] == DATA_CLASSIFICATION
    assert output["summary"]["directAssignedDemandCount"] == 2
    assert output["summary"]["substituteProposalCount"] == 1
    assert output["summary"]["productRetrievalGate"] == {
        "sourceProfileCount": 2,
        "functionEvidenceReadySourceCount": 2,
        "identityEligibleSourceCount": 1,
        "identityEligibleDirectedPairCount": 1,
        "primaryWindowSourceCount": 1,
        "fallbackWindowSourceCount": 0,
        "relationAssistedRowsDisabled": 1,
        "relationDeploymentStatus": "REQUIRES_DOMAIN_OWNER_SIGNOFF",
        "runtimeRelationPolicy": "IDENTITY_ONLY",
    }
    assert output["invariantChecks"]["status"] == "PASSED"
    assert output["invariantChecks"]["relationAssistedProposalCount"] == 0
    board = output["demandBoards"][0]
    assert board["participantCount"] == 2
    assert board["pendingSubstituteOfferCount"] == 1
    assert board["profileOrigin"] == PROFILE_ORIGIN

    snapshot = build_part_c_grounded_hourly_snapshot(output)

    assert snapshot["schemaVersion"] == "part-c-demand-board-snapshot.v0.4"
    assert snapshot["invariantChecks"]["status"] == "PASSED"
    assert "demandStates" not in snapshot
    assert "substituteAdmissionPlan" not in snapshot
    assert "catalogDisplayName" not in snapshot["demandBoards"][0]
    assert "substitutionEvidenceStatus" not in snapshot["demandBoards"][0]
    assert "semanticText" not in snapshot["demandBoards"][0]
