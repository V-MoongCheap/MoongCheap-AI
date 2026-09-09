"""Simulate the Part B demand-board flow as recurring hourly batches.

The Part A 5k fixture has no registration timestamps.  This simulator assigns
each demand a deterministic synthetic registration time within an explicit
arrival window, carries Backend-like demand and board state across batches,
and expires requests that remain unassigned for 48 hours.

The result is a mechanics scenario, not a forecast of production traffic.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from moongcheap_ai.demand_clustering import (
    DemandBoardInput,
    DemandInput,
    SubstituteBoardCandidateInput,
    SubstituteBoardAdmissionDecision,
    SubstituteDemandInput,
    build_substitute_board_admission_plan,
    character_ngram_cosine_similarity,
    plan_demand_clustering_batch,
    select_substitute_board_candidate,
)
from moongcheap_ai.demand_clustering.eligibility import (
    UNASSIGNED_CLUSTERING_WINDOW,
)
from moongcheap_ai.demand_constraints import DemandConstraintParser

from scripts.demand.simulate_demand_board_handoff import (
    PRICE_ORIGIN,
    PROFILE_ORIGIN,
    CodeCanonicalizer,
    _sha256,
    _stable_index,
    _source_price_is_official,
    build_synthetic_catalog_profiles,
    requirement_from_v046_row,
    simulated_price_band,
)


REGISTRATION_TIME_ORIGIN = "SYNTHETIC_STABLE_HASH_WITHIN_ARRIVAL_WINDOW"
DEFAULT_ARRIVAL_HOURS = 24
DEFAULT_BATCH_INTERVAL_MINUTES = 60
DEFAULT_DEMAND_LIFETIME_DAYS = 7
DEFAULT_BOARD_LIFETIME_DAYS = 5


def simulated_registration_time(
    source_demand_id: str,
    *,
    start_at: datetime,
    arrival_window: timedelta,
) -> datetime:
    """Place one demand reproducibly inside a half-open arrival window."""

    if start_at.tzinfo is None or start_at.utcoffset() is None:
        raise ValueError("start_at must include timezone information")
    window_seconds = int(arrival_window.total_seconds())
    if window_seconds < 1:
        raise ValueError("arrival_window must be at least one second")
    offset_seconds = _stable_index(
        f"registration:{source_demand_id}",
        window_seconds,
    )
    return start_at + timedelta(seconds=offset_seconds)


def _batch_times(
    *,
    start_at: datetime,
    arrival_window: timedelta,
    batch_interval: timedelta,
) -> tuple[datetime, ...]:
    interval_seconds = int(batch_interval.total_seconds())
    if interval_seconds < 1:
        raise ValueError("batch_interval must be at least one second")
    end_at = start_at + arrival_window + UNASSIGNED_CLUSTERING_WINDOW
    values = []
    current = start_at + batch_interval
    while current <= end_at:
        values.append(current)
        current += batch_interval
    return tuple(values)


def _board_input(board: Mapping[str, Any]) -> DemandBoardInput:
    return DemandBoardInput(
        id=int(board["demandBoardId"]),
        catalog_id=int(board["catalogId"]),
        participant_count=int(board["participantCount"]),
        created_at=datetime.fromisoformat(str(board["createdAt"])),
        sale_end_at=datetime.fromisoformat(str(board["saleEndAt"])),
        price_min=int(board["priceMin"]),
        price_max=int(board["priceMax"]),
        status=str(board["status"]),
    )


def _substitute_candidate(
    board: Mapping[str, Any],
    profile: Mapping[str, Any],
) -> SubstituteBoardCandidateInput:
    return SubstituteBoardCandidateInput(
        id=int(board["demandBoardId"]),
        catalog_id=int(board["catalogId"]),
        category_id=str(profile["categoryId"]),
        taxonomy_version=str(profile["taxonomyVersion"]),
        price_min=int(board["priceMin"]),
        price_max=int(board["priceMax"]),
        participant_count=int(board["participantCount"]),
        facet_values=profile["facetValues"],
        sale_end_at=datetime.fromisoformat(str(board["saleEndAt"])),
        status=str(board["status"]),
        semantic_text=str(profile["semanticText"]),
    )


def simulate_hourly_demand_board_handoff(
    source_rows: Iterable[Mapping[str, str]],
    taxonomy: Mapping[str, Any],
    *,
    start_at: datetime,
    arrival_window: timedelta,
    batch_interval: timedelta,
    min_participants: int,
    canonicalize_value_code: CodeCanonicalizer | None = None,
    catalog_profiles: Mapping[int, Mapping[str, Any]] | None = None,
    eligible_substitute_catalog_ids: Mapping[int, frozenset[int]] | None = None,
    product_gate_reasons: Mapping[int, tuple[str, ...]] | None = None,
    text_similarity_scorer: Callable[[str, str], float] | None = (
        character_ngram_cosine_similarity
    ),
) -> dict[str, Any]:
    """Run recurring clustering batches with persistent synthetic state."""

    if start_at.tzinfo is None or start_at.utcoffset() is None:
        raise ValueError("start_at must include timezone information")
    rows = tuple(dict(row) for row in source_rows)
    if not rows:
        raise ValueError("source demand rows must not be empty")
    source_ids = [row["demand_id"] for row in rows]
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("duplicate source demand id")

    if catalog_profiles is None:
        profiles = build_synthetic_catalog_profiles(
            rows,
            taxonomy,
            canonicalize_value_code=canonicalize_value_code,
        )
    else:
        profiles = {
            int(catalog_id): dict(profile)
            for catalog_id, profile in catalog_profiles.items()
        }
        required_catalog_ids = {int(row["product_reference"]) for row in rows}
        if missing := sorted(required_catalog_ids - set(profiles)):
            raise ValueError(
                "catalog profiles are missing demand products: "
                + ", ".join(str(value) for value in missing)
            )
    requirements = {}
    source_by_id: dict[int, dict[str, str]] = {}
    inputs_by_id: dict[int, DemandInput] = {}
    registration_by_id = {}
    states: dict[int, str] = {}
    assignment_type: dict[int, str] = {}
    assigned_board: dict[int, int | None] = {}
    reason_codes: dict[int, list[str]] = {}

    for demand_id, row in enumerate(rows, 1):
        registered_at = simulated_registration_time(
            row["demand_id"],
            start_at=start_at,
            arrival_window=arrival_window,
        )
        band = simulated_price_band(row["demand_id"])
        source_by_id[demand_id] = row
        registration_by_id[demand_id] = registered_at
        requirements[demand_id] = requirement_from_v046_row(row)
        inputs_by_id[demand_id] = DemandInput(
            id=demand_id,
            catalog_id=int(row["product_reference"]),
            created_at=registered_at,
            updated_at=registered_at,
            desired_price_min=band.lower_bound,
            desired_price_max=band.upper_bound,
            quantity=int(row["quantity"]),
            is_substitutable=str(row["is_substitutable"]).casefold() == "true",
            status="UNASSIGNED",
            label=str(row["label"]),
            desire_end_at=registered_at + timedelta(days=DEFAULT_DEMAND_LIFETIME_DAYS),
            processed_at=registered_at,
        )
        states[demand_id] = "UNASSIGNED"
        assignment_type[demand_id] = "NONE"
        assigned_board[demand_id] = None
        reason_codes[demand_id] = []

    boards: dict[int, dict[str, Any]] = {}
    next_board_id = 1_000_001
    proposals: list[dict[str, Any]] = []
    proposal_batch_by_demand: dict[int, str] = {}
    batch_timeline = []
    previous_batch_at = start_at

    for batch_number, batch_at in enumerate(
        _batch_times(
            start_at=start_at,
            arrival_window=arrival_window,
            batch_interval=batch_interval,
        ),
        1,
    ):
        batch_id = f"hourly-demand-clustering-{batch_at.strftime('%Y%m%dT%H%M%S%z')}"
        newly_registered = tuple(
            demand_id
            for demand_id, registered_at in registration_by_id.items()
            if previous_batch_at <= registered_at < batch_at
        )
        active_board_rows = tuple(
            _board_input(board)
            for board in boards.values()
            if (
                board["status"] == "GB_GATHERING"
                and datetime.fromisoformat(board["saleEndAt"]) > batch_at
            )
        )
        unassigned_inputs = tuple(
            item
            for demand_id, item in inputs_by_id.items()
            if states[demand_id] == "UNASSIGNED" and item.created_at < batch_at
        )
        clustering_plan = plan_demand_clustering_batch(
            unassigned_inputs,
            active_board_rows,
            as_of=batch_at,
            min_participants=min_participants,
        )

        existing_assigned_count = 0
        for plan in clustering_plan.existing_board_assignments:
            board = boards[plan.demand_board_id]
            board["participantCount"] += plan.participant_count_delta
            board["directDemandIds"].extend(plan.demand_ids)
            board["directDemandIds"].sort()
            for demand_id in plan.demand_ids:
                states[demand_id] = "ASSIGNED"
                assignment_type[demand_id] = "ORIGINAL_CATALOG"
                assigned_board[demand_id] = plan.demand_board_id
                reason_codes[demand_id] = []
            existing_assigned_count += plan.participant_count_delta

        new_board_assigned_count = 0
        new_board_ids = []
        for plan in clustering_plan.new_board_plans:
            board_id = next_board_id
            next_board_id += 1
            profile = profiles[plan.catalog_id]
            board = {
                "demandBoardId": board_id,
                "catalogId": plan.catalog_id,
                "catalogDisplayName": profile["catalogDisplayName"],
                "categoryId": profile["categoryId"],
                "taxonomyVersion": profile["taxonomyVersion"],
                "priceMin": plan.price_min,
                "priceMax": plan.price_max,
                "participantCount": plan.participant_count,
                "pendingSubstituteOfferCount": 0,
                "status": "GB_GATHERING",
                "createdAt": batch_at.isoformat(),
                "saleEndAt": (
                    batch_at + timedelta(days=DEFAULT_BOARD_LIFETIME_DAYS)
                ).isoformat(),
                "directDemandIds": list(plan.demand_ids),
                "pendingSubstituteDemandIds": [],
                "facetValues": profile["facetValues"],
                "semanticText": profile["semanticText"],
                "profileOrigin": profile.get("profileOrigin", PROFILE_ORIGIN),
            }
            if "substitutionEvidenceStatus" in profile:
                board["substitutionEvidenceStatus"] = profile[
                    "substitutionEvidenceStatus"
                ]
            boards[board_id] = board
            new_board_ids.append(board_id)
            for demand_id in plan.demand_ids:
                states[demand_id] = "ASSIGNED"
                assignment_type[demand_id] = "ORIGINAL_CATALOG"
                assigned_board[demand_id] = board_id
                reason_codes[demand_id] = []
            new_board_assigned_count += plan.participant_count

        substitute_candidates = tuple(
            _substitute_candidate(board, profiles[int(board["catalogId"])])
            for board in boards.values()
            if (
                board["status"] == "GB_GATHERING"
                and datetime.fromisoformat(board["saleEndAt"]) > batch_at
            )
        )
        admission_items = []
        for demand_id, item in inputs_by_id.items():
            if (
                states[demand_id] != "UNASSIGNED"
                or item.created_at >= batch_at
                or not item.is_substitutable
                or item.created_at + UNASSIGNED_CLUSTERING_WINDOW <= batch_at
            ):
                continue
            row = source_by_id[demand_id]
            current = SubstituteDemandInput.from_demand(
                item,
                category_id=row["category_id"],
                taxonomy_version=row.get(
                    "taxonomy_version",
                    str(taxonomy.get("version", taxonomy.get("taxonomy_version", ""))),
                ),
                requirement=requirements[demand_id],
            )
            candidate_pool = substitute_candidates
            if eligible_substitute_catalog_ids is not None:
                allowed_catalog_ids = eligible_substitute_catalog_ids.get(
                    item.catalog_id,
                    frozenset(),
                )
                if not allowed_catalog_ids:
                    gate_reasons = (
                        product_gate_reasons or {}
                    ).get(
                        item.catalog_id,
                        ("NO_IDENTITY_COVERAGE_CANDIDATE_IN_TOP20",),
                    )
                    decision = SubstituteBoardAdmissionDecision(
                        demand_id=current.id,
                        status="NO_ELIGIBLE_SUBSTITUTE_PRODUCT",
                        reason_codes=(
                            "NO_ELIGIBLE_SUBSTITUTE_PRODUCT",
                            *gate_reasons,
                        ),
                        ranked_boards=(),
                        rejected_boards=(),
                    )
                    admission_items.append((current, decision))
                    reason_codes[demand_id] = list(decision.reason_codes)
                    continue
                candidate_pool = tuple(
                    candidate
                    for candidate in substitute_candidates
                    if candidate.catalog_id in allowed_catalog_ids
                )
            decision = select_substitute_board_candidate(
                current,
                candidate_pool,
                as_of=batch_at,
                canonicalize_value_code=canonicalize_value_code,
                text_similarity_scorer=text_similarity_scorer,
            )
            if not decision.ranked_boards and decision.rejected_boards:
                detailed_reasons = tuple(dict.fromkeys(
                    reason
                    for rejected in decision.rejected_boards
                    for reason in rejected.reason_codes
                ))
                decision = SubstituteBoardAdmissionDecision(
                    demand_id=decision.demand_id,
                    status=decision.status,
                    reason_codes=(
                        *decision.reason_codes,
                        *detailed_reasons,
                    ),
                    ranked_boards=decision.ranked_boards,
                    rejected_boards=decision.rejected_boards,
                )
            admission_items.append((current, decision))
            reason_codes[demand_id] = list(decision.reason_codes)

        batch_admission = build_substitute_board_admission_plan(
            admission_items,
            batch_id=batch_id,
            planned_at=batch_at,
            rule_version="requirement-v0.46+hourly-board-formation-v0.2+admission-v0.1",
            text_scorer_version="character-bigram-cosine-fixture-only",
        )
        for proposal in batch_admission["proposals"]:
            demand_id = int(proposal["demandId"])
            board_id = int(proposal["demandBoardId"])
            enriched = dict(proposal)
            enriched["offeredAt"] = batch_at.isoformat()
            enriched["batchId"] = batch_id
            proposals.append(enriched)
            proposal_batch_by_demand[demand_id] = batch_id
            states[demand_id] = "SUBSTITUTE_OFFERED"
            assignment_type[demand_id] = "SUBSTITUTE_PROPOSAL"
            assigned_board[demand_id] = board_id
            reason_codes[demand_id] = []
            boards[board_id]["pendingSubstituteDemandIds"].append(demand_id)
            boards[board_id]["pendingSubstituteOfferCount"] += 1

        expired_this_batch = 0
        for demand_id, item in inputs_by_id.items():
            if (
                states[demand_id] == "UNASSIGNED"
                and item.created_at + UNASSIGNED_CLUSTERING_WINDOW <= batch_at
            ):
                states[demand_id] = "EXPIRED"
                assignment_type[demand_id] = "NONE"
                assigned_board[demand_id] = None
                if item.is_substitutable:
                    previous_reasons = reason_codes[demand_id] or [
                        "NO_COMPATIBLE_BOARD"
                    ]
                    reason_codes[demand_id] = list(dict.fromkeys((
                        *previous_reasons,
                        "UNASSIGNED_WINDOW_EXPIRED",
                    )))
                else:
                    reason_codes[demand_id] = [
                        "SUBSTITUTION_NOT_CONSENTED",
                        "UNASSIGNED_WINDOW_EXPIRED",
                    ]
                expired_this_batch += 1

        registered_state_counts = Counter(
            states[demand_id]
            for demand_id, registered_at in registration_by_id.items()
            if registered_at < batch_at
        )
        unregistered_count = len(states) - sum(registered_state_counts.values())
        if unregistered_count:
            registered_state_counts["UNREGISTERED"] = unregistered_count
        batch_timeline.append({
            "batchNumber": batch_number,
            "batchId": batch_id,
            "plannedAt": batch_at.isoformat(),
            "newlyRegisteredDemandCount": len(newly_registered),
            "unassignedInputCount": len(unassigned_inputs),
            "existingBoardAssignedCount": existing_assigned_count,
            "newBoardCount": len(new_board_ids),
            "newBoardIds": new_board_ids,
            "newBoardAssignedCount": new_board_assigned_count,
            "substituteProposalCount": len(batch_admission["proposals"]),
            "expiredDemandCount": expired_this_batch,
            "cumulativeStateCounts": dict(sorted(registered_state_counts.items())),
        })
        previous_batch_at = batch_at

    final_batch_at = batch_timeline[-1]["plannedAt"]
    not_eligible = []
    unmatched = []
    for demand_id, item in inputs_by_id.items():
        if states[demand_id] in {"ASSIGNED", "SUBSTITUTE_OFFERED"}:
            continue
        target = unmatched if item.is_substitutable else not_eligible
        target.append({
            "demandId": demand_id,
            "reasonCodes": reason_codes[demand_id],
        })

    demand_states = []
    for demand_id, item in inputs_by_id.items():
        row = source_by_id[demand_id]
        band = simulated_price_band(row["demand_id"])
        demand_states.append({
            "demandId": demand_id,
            "sourceDemandId": row["demand_id"],
            "originalCatalogId": item.catalog_id,
            "categoryId": row["category_id"],
            "registeredAt": item.created_at.isoformat(),
            "processedAt": item.processed_at.isoformat() if item.processed_at else None,
            "status": states[demand_id],
            "assignmentType": assignment_type[demand_id],
            "demandBoardId": assigned_board[demand_id],
            "proposalBatchId": proposal_batch_by_demand.get(demand_id),
            "quantity": item.quantity,
            "isSubstitutable": item.is_substitutable,
            "requirementStatus": requirements[demand_id].status,
            "effectiveRequirementMode": requirements[
                demand_id
            ].effective_requirement_mode,
            "sourceDesiredPriceMin": row.get("desired_price_min", ""),
            "sourceDesiredPriceMax": row.get("desired_price_max", ""),
            "desiredPriceMin": band.lower_bound,
            "desiredPriceMax": band.upper_bound,
            "priceOrigin": PRICE_ORIGIN,
            "reasonCodes": reason_codes[demand_id],
        })

    mode_counts = Counter(
        value.effective_requirement_mode for value in requirements.values()
    )
    requirement_counts = Counter(value.status for value in requirements.values())
    state_counts = Counter(states.values())
    direct_count = state_counts["ASSIGNED"]
    offered_count = state_counts["SUBSTITUTE_OFFERED"]
    return {
        "schemaVersion": "part-c-demand-board-hourly-simulation.v0.2",
        "dataClassification": "SYNTHETIC_MECHANICS_ONLY_NOT_PRODUCT_FACT",
        "generatedAt": final_batch_at,
        "consumerNotice": (
            "Part C may use this to exercise hourly board/seller matching mechanics. "
            "Registration times, catalog facets, semantic text, and regenerated "
            "prices are synthetic."
        ),
        "simulationPolicy": {
            "minParticipants": min_participants,
            "batchIntervalMinutes": int(batch_interval.total_seconds() // 60),
            "simulationStartAt": start_at.isoformat(),
            "arrivalWindowHours": int(arrival_window.total_seconds() // 3600),
            "arrivalWindowEndExclusive": (start_at + arrival_window).isoformat(),
            "registrationTimeOrigin": REGISTRATION_TIME_ORIGIN,
            "clusteringWindowHours": int(
                UNASSIGNED_CLUSTERING_WINDOW.total_seconds() // 3600
            ),
            "demandLifetimeDays": DEFAULT_DEMAND_LIFETIME_DAYS,
            "boardLifetimeDays": DEFAULT_BOARD_LIFETIME_DAYS,
            "priceOrigin": PRICE_ORIGIN,
            "catalogProfileOrigin": PROFILE_ORIGIN,
            "priceRule": "official seven bands selected by stable demand-id hash",
            "profileRule": (
                "one taxonomy value per facet selected by stable catalog-id hash"
            ),
            "substituteConfirmation": (
                "not simulated; proposals remain SUBSTITUTE_OFFERED"
            ),
            "participantCountIncludesPendingOffers": False,
            "sellerDataIncluded": False,
        },
        "summary": {
            "sourceDemandCount": len(inputs_by_id),
            "catalogProfileCount": len(profiles),
            "sourcePriceContractViolationCount": sum(
                not _source_price_is_official(row) for row in rows
            ),
            "batchCount": len(batch_timeline),
            "demandBoardCount": len(boards),
            "directAssignedDemandCount": direct_count,
            "substituteProposalCount": offered_count,
            "substitutionNotEligibleCount": len(not_eligible),
            "unmatchedDemandCount": len(unmatched),
            "expiredDemandCount": state_counts["EXPIRED"],
            "reviewQueueCount": 0,
            "finalDemandStatusCounts": dict(sorted(state_counts.items())),
            "requirementStatusCounts": dict(sorted(requirement_counts.items())),
            "effectiveRequirementModeCounts": dict(sorted(mode_counts.items())),
        },
        "batchTimeline": batch_timeline,
        "catalogProfiles": list(profiles.values()),
        "demandBoards": list(boards.values()),
        "substituteAdmissionPlan": {
            "schemaVersion": "substitute-board-admission-plan.v0.1",
            "ruleVersion": (
                "requirement-v0.46+hourly-board-formation-v0.2+admission-v0.1"
            ),
            "proposals": proposals,
            "notEligible": not_eligible,
            "unmatched": unmatched,
            "stateContract": {
                "proposal": "UNASSIGNED_TO_SUBSTITUTE_OFFERED",
                "accept": "SUBSTITUTE_OFFERED_TO_ASSIGNED",
                "reject": "SUBSTITUTE_OFFERED_TO_UNASSIGNED",
                "proposalIncrementsParticipantCount": False,
            },
        },
        "demandStates": demand_states,
    }


def build_part_c_hourly_board_snapshot(
    simulation: Mapping[str, Any],
) -> dict[str, Any]:
    """Remove demand-level diagnostics from the hourly Part C handoff."""

    return {
        "schemaVersion": "part-c-demand-board-snapshot.v0.2",
        "dataClassification": simulation["dataClassification"],
        "generatedAt": simulation["generatedAt"],
        "consumerNotice": simulation["consumerNotice"],
        "sourceSummary": simulation["summary"],
        "simulationPolicy": simulation["simulationPolicy"],
        "batchTimeline": simulation["batchTimeline"],
        "demandBoards": simulation["demandBoards"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a synthetic hourly 5k demand-board handoff for Part C"
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--taxonomy", type=Path, required=True)
    parser.add_argument(
        "--rules",
        type=Path,
        default=Path("config/demand_constraint_rules.json"),
    )
    parser.add_argument(
        "--aliases",
        type=Path,
        default=Path("config/demand_constraint_aliases.json"),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--board-output", type=Path)
    parser.add_argument("--start-at", default="2026-09-05T00:00:00+09:00")
    parser.add_argument("--arrival-hours", type=int, default=DEFAULT_ARRIVAL_HOURS)
    parser.add_argument(
        "--batch-interval-minutes",
        type=int,
        default=DEFAULT_BATCH_INTERVAL_MINUTES,
    )
    parser.add_argument("--min-participants", type=int, default=5)
    parser.add_argument(
        "--allow-synthetic-catalog-profiles",
        action="store_true",
        help="Required acknowledgement that generated profiles are not product facts",
    )
    parser.add_argument(
        "--allow-synthetic-registration-times",
        action="store_true",
        help="Required acknowledgement that source rows have no registration times",
    )
    args = parser.parse_args()
    if not args.allow_synthetic_catalog_profiles:
        parser.error("--allow-synthetic-catalog-profiles is required")
    if not args.allow_synthetic_registration_times:
        parser.error("--allow-synthetic-registration-times is required")
    if args.arrival_hours < 1:
        parser.error("--arrival-hours must be positive")
    if args.batch_interval_minutes < 1:
        parser.error("--batch-interval-minutes must be positive")

    taxonomy = json.loads(args.taxonomy.read_text(encoding="utf-8"))
    requirement_parser = DemandConstraintParser.from_taxonomy(
        taxonomy,
        rules_path=args.rules,
        aliases_path=args.aliases,
    )
    with args.input.open(encoding="utf-8-sig", newline="") as source:
        rows = tuple(csv.DictReader(source))
    start_at = datetime.fromisoformat(args.start_at.replace("Z", "+00:00"))
    output = simulate_hourly_demand_board_handoff(
        rows,
        taxonomy,
        start_at=start_at,
        arrival_window=timedelta(hours=args.arrival_hours),
        batch_interval=timedelta(minutes=args.batch_interval_minutes),
        min_participants=args.min_participants,
        canonicalize_value_code=requirement_parser.canonicalize_value_code,
    )
    output["source"] = {
        "demandInput": str(args.input.resolve()),
        "demandInputSha256": _sha256(args.input),
        "taxonomy": str(args.taxonomy.resolve()),
        "taxonomySha256": _sha256(args.taxonomy),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if args.board_output is not None:
        args.board_output.parent.mkdir(parents=True, exist_ok=True)
        args.board_output.write_text(
            json.dumps(
                build_part_c_hourly_board_snapshot(output),
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    print(json.dumps({
        "output": str(args.output),
        "boardOutput": str(args.board_output) if args.board_output else None,
        **output["summary"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
