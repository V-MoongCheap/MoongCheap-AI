"""Validated HTTP handoff for Backend-owned substitute offer mutations."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests

from .backend_http import (
    aware_datetime as _aware_datetime,
    exact_fields as _exact_fields,
    iter_plan_requests,
    nonnegative_int as _nonnegative_int,
    positive_int as _positive_int,
    post_plan_json,
    required_fields as _required_fields,
)

PLAN_SCHEMA_VERSION = "substitute-offer-plan.v0.1"
PLAN_ENDPOINT = "/api/demand-boards/internal/substitute-offer-plans"
# Use the Backend team's announced limit, even if a deployed DTO permits more.
MAX_SUBSTITUTE_PROPOSALS = 50

PLAN_FIELDS = {
    "schemaVersion",
    "plannedAt",
    "ruleVersion",
    "proposals",
}
PROPOSAL_FIELDS = {
    "demandId",
    "expectedOriginalCatalogId",
    "substituteCatalogId",
    "demandBoardId",
}


@dataclass(frozen=True, slots=True)
class BackendPlanApplyResult:
    status: str
    applied_count: int
    already_applied_count: int
    stale_rejected_count: int


def validate_backend_plan_contract(plan: Mapping[str, Any]) -> None:
    """Reject a malformed minimal offer request before an HTTP mutation."""

    if "reviewRequired" in plan:
        raise ValueError("runtime plan must not contain reviewRequired")
    _exact_fields(plan, PLAN_FIELDS, "plan")
    if plan.get("schemaVersion") != PLAN_SCHEMA_VERSION:
        raise ValueError("unsupported substitute offer plan schema")

    rule_version = plan["ruleVersion"]
    if (
        not isinstance(rule_version, str)
        or not rule_version.strip()
        or len(rule_version) > 200
    ):
        raise ValueError("ruleVersion must be a nonempty string of at most 200 characters")
    _aware_datetime(plan["plannedAt"], "plannedAt")
    if not isinstance(plan["proposals"], list):
        raise ValueError("proposals must be an array")

    demand_ids: set[int] = set()
    for index, proposal in enumerate(plan["proposals"]):
        context = f"proposals[{index}]"
        if not isinstance(proposal, Mapping):
            raise ValueError(f"{context} must be a JSON object")
        _exact_fields(proposal, PROPOSAL_FIELDS, context)
        demand_id = _positive_int(proposal["demandId"], f"{context}.demandId")
        if demand_id in demand_ids:
            raise ValueError(f"duplicate demandId: {demand_id}")
        demand_ids.add(demand_id)
        original_catalog_id = _positive_int(
            proposal["expectedOriginalCatalogId"],
            f"{context}.expectedOriginalCatalogId",
        )
        substitute_catalog_id = _positive_int(
            proposal["substituteCatalogId"], f"{context}.substituteCatalogId"
        )
        _positive_int(proposal["demandBoardId"], f"{context}.demandBoardId")
        if original_catalog_id == substitute_catalog_id:
            raise ValueError(f"{context} substitute catalog must differ")


def build_substitute_offer_plan_request(
    proposals: Iterable[Mapping[str, Any]],
    *,
    planned_at: datetime | str,
    rule_version: str,
) -> dict[str, Any]:
    """Project rich AI decisions onto the minimal Backend mutation DTO."""

    projected = []
    for proposal in proposals:
        projected.append({
            "demandId": proposal.get("demandId"),
            "expectedOriginalCatalogId": proposal.get("originalCatalogId"),
            "substituteCatalogId": proposal.get("substituteCatalogId"),
            "demandBoardId": proposal.get("demandBoardId"),
        })
    request = {
        "schemaVersion": PLAN_SCHEMA_VERSION,
        "plannedAt": _aware_datetime(planned_at, "plannedAt").isoformat(),
        "ruleVersion": rule_version,
        "proposals": projected,
    }
    validate_backend_plan_contract(request)
    request["proposals"].sort(key=lambda row: row["demandId"])
    return request


def iter_substitute_offer_requests(
    plan: Mapping[str, Any],
) -> Iterator[dict[str, Any]]:
    """Validate the whole logical plan, then emit bounded wire requests."""

    validate_backend_plan_contract(plan)
    yield from iter_plan_requests(plan, {"proposals": MAX_SUBSTITUTE_PROPOSALS})


def post_substitute_board_admission_plan(
    backend_base_url: str,
    internal_key: str,
    plan: Mapping[str, Any],
    *,
    endpoint: str = PLAN_ENDPOINT,
    timeout_seconds: int = 15,
    http_post: Callable[..., Any] = requests.post,
) -> BackendPlanApplyResult:
    """Send bounded requests sequentially; validate and sum every response.

    Failures stop subsequent requests without retry or rollback of earlier
    Backend commits. The next scheduled batch reads current database state.
    """

    applied = 0
    already_applied = 0
    stale_rejected = 0
    for request in iter_substitute_offer_requests(plan):
        payload = post_plan_json(
            backend_base_url,
            internal_key,
            request,
            endpoint=endpoint,
            timeout_seconds=timeout_seconds,
            http_post=http_post,
            context="Backend clustering plan apply",
        )
        result = _parse_substitute_offer_response(payload, request)
        applied += result.applied_count
        already_applied += result.already_applied_count
        stale_rejected += result.stale_rejected_count
    return BackendPlanApplyResult(
        status="APPLIED",
        applied_count=applied,
        already_applied_count=already_applied,
        stale_rejected_count=stale_rejected,
    )


def _parse_substitute_offer_response(
    payload: Mapping[str, Any],
    plan: Mapping[str, Any],
) -> BackendPlanApplyResult:
    _required_fields(
        payload,
        {
            "status",
            "appliedCount",
            "alreadyAppliedCount",
            "staleRejectedCount",
        },
        "Backend apply response",
    )
    status = payload.get("status")
    if status != "APPLIED":
        raise ValueError(f"unknown Backend apply status: {status}")

    counts: dict[str, int] = {}
    for field in (
        "appliedCount",
        "alreadyAppliedCount",
        "staleRejectedCount",
    ):
        counts[field] = _nonnegative_int(
            payload.get(field), f"Backend response {field}"
        )
    if (
        counts["appliedCount"]
        + counts["alreadyAppliedCount"]
        + counts["staleRejectedCount"]
        != len(plan["proposals"])
    ):
        raise ValueError("Backend proposal outcome counts do not add up")

    return BackendPlanApplyResult(
        status=str(status),
        applied_count=counts["appliedCount"],
        already_applied_count=counts["alreadyAppliedCount"],
        stale_rejected_count=counts["staleRejectedCount"],
    )
