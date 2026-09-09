"""Validated HTTP handoff for Backend-owned substitute offer mutations."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests

from .backend_http import (
    aware_datetime as _aware_datetime,
    exact_fields as _exact_fields,
    nonnegative_int as _nonnegative_int,
    positive_int as _positive_int,
    post_plan_json,
    required_fields as _required_fields,
)

PLAN_SCHEMA_VERSION = "substitute-offer-plan.v0.1"
PLAN_ENDPOINT = "/api/demand-boards/internal/substitute-offer-plans"

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


def post_substitute_board_admission_plan(
    backend_base_url: str,
    internal_key: str,
    plan: Mapping[str, Any],
    *,
    endpoint: str = PLAN_ENDPOINT,
    timeout_seconds: int = 15,
    http_post: Callable[..., Any] = requests.post,
) -> BackendPlanApplyResult:
    """Submit once and validate the Backend's state-based application counts."""

    validate_backend_plan_contract(plan)
    payload = post_plan_json(
        backend_base_url,
        internal_key,
        plan,
        endpoint=endpoint,
        timeout_seconds=timeout_seconds,
        http_post=http_post,
        context="Backend clustering plan apply",
    )
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
