from __future__ import annotations

import json
from pathlib import Path

import pytest
import requests
from jsonschema import Draft202012Validator, ValidationError

from moongcheap_ai.demand_clustering.backend_board_plan import (
    post_board_assignment_plan,
    validate_board_assignment_plan_contract,
)
from moongcheap_ai.demand_clustering.backend_plan_client import (
    post_substitute_board_admission_plan,
    validate_backend_plan_contract,
)

from .test_backend_board_plan import FormationResponse, formation_plan
from .test_backend_plan_client import Response, plan


@pytest.fixture(params=["formation", "substitution"])
def contract(request):
    if request.param == "formation":
        return (
            formation_plan, post_board_assignment_plan, FormationResponse,
            validate_board_assignment_plan_contract,
            "demand_board_assignment_plan_v01.schema.json",
        )
    return (
        plan, post_substitute_board_admission_plan, Response,
        validate_backend_plan_contract, "substitute_offer_plan_v01.schema.json",
    )


def test_legacy_batch_id_is_rejected_by_request_validator_and_schema(contract):
    make_plan, _, _, validate, schema_name = contract
    payload = make_plan()
    assert "batchId" not in payload
    payload["batchId"] = "obsolete-replay-key"

    with pytest.raises(ValueError, match="batchId"):
        validate(payload)
    schema = json.loads((Path("docs/contracts") / schema_name).read_text())
    with pytest.raises(ValidationError, match="batchId"):
        Draft202012Validator(schema).validate(payload)


def test_lost_response_is_propagated_without_http_retry(contract):
    make_plan, post, _, _, _ = contract
    calls = []

    def fail(url, **kwargs):
        calls.append(kwargs)
        raise requests.Timeout("response not received")

    with pytest.raises(requests.Timeout):
        post("https://backend.example", "internal-secret", make_plan(), http_post=fail)

    assert len(calls) == 1
    assert calls[0]["headers"] == {
        "X-Internal-Key": "internal-secret",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    assert calls[0]["allow_redirects"] is False


@pytest.mark.parametrize("status_code", [307, 308, 500])
def test_redirects_and_http_errors_fail_without_resending_or_exposing_key(
    contract, status_code
):
    make_plan, post, response_type, _, _ = contract
    response = response_type()
    response.status_code = status_code
    response.ok = status_code < 400
    response.text = "request rejected: X-Internal-Key=internal-secret"
    calls = []

    def respond(url, **kwargs):
        calls.append(kwargs)
        return response

    with pytest.raises(RuntimeError, match=f"HTTP {status_code}") as error:
        post("https://backend.example", "internal-secret", make_plan(), http_post=respond)

    assert "internal-secret" not in str(error.value)
    assert "[REDACTED]" in str(error.value)
    assert len(calls) == 1
    assert calls[0]["allow_redirects"] is False


def test_replayed_response_is_no_longer_a_supported_result(contract):
    make_plan, post, response_type, _, _ = contract

    class ReplayedResponse(response_type):
        def json(self):
            payload = super().json()
            payload["status"] = "REPLAYED"
            return payload

    with pytest.raises(ValueError, match="status"):
        post(
            "https://backend.example", "internal-secret", make_plan(),
            http_post=lambda *args, **kwargs: ReplayedResponse(),
        )


def test_empty_internal_key_fails_before_sending(contract):
    make_plan, post, _, _, _ = contract

    def unexpected_post(*args, **kwargs):
        raise AssertionError("missing key must prevent HTTP")

    with pytest.raises(ValueError, match="internal_key must not be empty"):
        post("https://backend.example", " ", make_plan(), http_post=unexpected_post)


def test_current_state_stale_result_does_not_require_original_board_mapping():
    class StaleResponse(FormationResponse):
        def json(self):
            payload = super().json()
            payload["existingAssignments"] = {"appliedCount": 0, "staleCount": 1}
            payload["newBoards"][0].update(
                status="STALE_REJECTED", demandBoardId=None
            )
            return payload

    result = post_board_assignment_plan(
        "https://backend.example", "internal-secret", formation_plan(),
        http_post=lambda *args, **kwargs: StaleResponse(),
    )
    assert result.status == "APPLIED"
    assert result.existing_stale_rejected_count == 1
    assert result.new_boards[0].demand_board_id is None


def test_current_identical_offer_can_still_count_as_already_applied():
    class ExistingOfferResponse(Response):
        def json(self):
            payload = super().json()
            payload.update(appliedCount=0, alreadyAppliedCount=1)
            return payload

    result = post_substitute_board_admission_plan(
        "https://backend.example", "internal-secret", plan(),
        http_post=lambda *args, **kwargs: ExistingOfferResponse(),
    )
    assert result.status == "APPLIED"
    assert result.applied_count == 0
    assert result.already_applied_count == 1
