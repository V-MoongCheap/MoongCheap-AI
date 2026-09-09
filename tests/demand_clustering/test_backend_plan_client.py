from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from moongcheap_ai.demand_clustering.evaluation.backend_requests import (
    build_backend_plan_request_bundle,
)
from moongcheap_ai.demand_clustering.backend_plan_client import (
    PLAN_ENDPOINT,
    build_substitute_offer_plan_request,
    post_substitute_board_admission_plan,
    validate_backend_plan_contract,
)


def proposal(*, demand_id: int = 1) -> dict[str, object]:
    return {
        "demandId": demand_id,
        "expectedOriginalCatalogId": 101,
        "substituteCatalogId": 201,
        "demandBoardId": 31,
    }


def source_proposal(*, demand_id: int = 1) -> dict[str, object]:
    return {
        "demandId": demand_id,
        "originalCatalogId": 101,
        "substituteCatalogId": 201,
        "demandBoardId": 31,
        "rankEvidence": {
            "demandBoardId": 31,
            "catalogId": 201,
            "rank": 1,
            "structuredPreferenceMatched": 1,
            "structuredPreferenceTotal": 1,
            "structuredPreferenceScore": 1.0,
            "textSimilarityScore": 0.9,
            "participantCount": 10,
            "matchedPreferences": ["product_form:capsule"],
            "unmatchedPreferences": [],
        },
    }


def plan() -> dict[str, object]:
    return {
        "schemaVersion": "substitute-offer-plan.v0.1",
        "plannedAt": "2026-09-06T12:00:00+09:00",
        "ruleVersion": "requirement-v0.46+admission-v0.1",
        "proposals": [proposal()],
    }


class Response:
    ok = True
    status_code = 200
    text = ""

    def json(self) -> dict[str, object]:
        return {
            "status": "APPLIED",
            "appliedCount": 1,
            "alreadyAppliedCount": 0,
            "staleRejectedCount": 0,
        }


def test_post_uses_internal_contract_and_validates_result() -> None:
    captured: dict[str, object] = {}

    def http_post(url: str, **kwargs: object) -> Response:
        captured["url"] = url
        captured.update(kwargs)
        return Response()

    result = post_substitute_board_admission_plan(
        "http://backend:8080/", "secret", plan(), http_post=http_post
    )

    assert captured["url"] == "http://backend:8080" + PLAN_ENDPOINT
    assert captured["headers"]["X-Internal-Key"] == "secret"
    assert "Authorization" not in captured["headers"]
    assert result.applied_count == 1


def test_minimal_offer_plan_matches_json_schema() -> None:
    schema_path = Path("docs/contracts/substitute_offer_plan_v01.schema.json")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    Draft202012Validator(
        schema,
        format_checker=FormatChecker(),
    ).validate(plan())


def test_projects_rich_ai_evidence_out_of_backend_request() -> None:
    request = build_substitute_offer_plan_request(
        [source_proposal()],
        planned_at="2026-09-06T12:00:00+09:00",
        rule_version="rules-v1",
    )

    assert request["proposals"] == [proposal()]
    assert "rankEvidence" not in request["proposals"][0]


def test_runtime_review_bucket_is_rejected_locally() -> None:
    invalid = plan()
    invalid["reviewRequired"] = []

    with pytest.raises(ValueError, match="reviewRequired"):
        validate_backend_plan_contract(invalid)


def test_response_outcome_counts_must_add_up() -> None:
    class InvalidResponse(Response):
        def json(self) -> dict[str, object]:
            payload = super().json()
            payload["appliedCount"] = 0
            return payload

    with pytest.raises(ValueError, match="counts do not add up"):
        post_substitute_board_admission_plan(
            "http://backend:8080",
            "secret",
            plan(),
            http_post=lambda *args, **kwargs: InvalidResponse(),
        )


def test_response_allows_additional_backend_metadata() -> None:
    class ExtendedResponse(Response):
        def json(self) -> dict[str, object]:
            payload = super().json()
            payload["processedAt"] = "2026-09-06T12:00:01+09:00"
            return payload

    result = post_substitute_board_admission_plan(
        "http://backend:8080",
        "secret",
        plan(),
        http_post=lambda *args, **kwargs: ExtendedResponse(),
    )

    assert result.applied_count == 1


def test_builds_one_valid_request_per_proposal_batch() -> None:
    second = source_proposal(demand_id=2)
    second["batchId"] = "batch-2"
    second["offeredAt"] = "2026-09-06T13:00:00+09:00"
    first = source_proposal()
    first["batchId"] = "batch-1"
    first["offeredAt"] = "2026-09-06T12:00:00+09:00"
    simulation = {
        "schemaVersion": "part-c-demand-board-hourly-simulation.v0.4",
        "simulationPolicy": {"textScorerVersion": "e5-small.v1"},
        "batchTimeline": [
            {"batchId": "batch-1", "plannedAt": "2026-09-06T12:00:00+09:00"},
            {"batchId": "batch-2", "plannedAt": "2026-09-06T13:00:00+09:00"},
        ],
        "substituteAdmissionPlan": {
            "schemaVersion": "substitute-board-admission-plan.v0.1",
            "ruleVersion": "rules-v1",
            "proposals": [second, first],
            "notEligible": [{"demandId": 3, "reasonCodes": ["NO_CONSENT"]}],
            "unmatched": [{"demandId": 4, "reasonCodes": ["NO_BOARD"]}],
        },
    }

    bundle = build_backend_plan_request_bundle(simulation)

    assert bundle["requestCount"] == 2
    assert bundle["proposalCount"] == 2
    assert bundle["diagnosticCounts"] == {"notEligible": 1, "unmatched": 1}
    assert [item["plannedAt"] for item in bundle["requests"]] == [
        "2026-09-06T12:00:00+09:00",
        "2026-09-06T13:00:00+09:00",
    ]
    assert all("batchId" not in request for request in bundle["requests"])
    assert bundle["requests"][0]["proposals"][0] == proposal()
    assert "rankEvidence" not in bundle["requests"][0]["proposals"][0]
    for request in bundle["requests"]:
        validate_backend_plan_contract(request)


def test_bundle_rejects_proposal_time_outside_its_batch() -> None:
    item = source_proposal()
    item["batchId"] = "batch-1"
    item["offeredAt"] = "2026-09-06T12:01:00+09:00"
    simulation = {
        "schemaVersion": "simulation.v1",
        "simulationPolicy": {"textScorerVersion": None},
        "batchTimeline": [
            {"batchId": "batch-1", "plannedAt": "2026-09-06T12:00:00+09:00"}
        ],
        "substituteAdmissionPlan": {
            "schemaVersion": "substitute-board-admission-plan.v0.1",
            "ruleVersion": "rules-v1",
            "proposals": [deepcopy(item)],
            "notEligible": [],
            "unmatched": [],
        },
    }

    with pytest.raises(ValueError, match="offeredAt"):
        build_backend_plan_request_bundle(simulation)
