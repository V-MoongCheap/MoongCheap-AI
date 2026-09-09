"""Build a deterministic 5k demand-board mechanics handoff for Part C.

The source demands and v0.46 requirement signals are retained, but missing
catalog facts and invalid synthetic price ranges are replaced with explicitly
marked simulation values.  The output must not be treated as product truth or
as a clustering-quality evaluation.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from moongcheap_ai.demand_clustering import (
    PRICE_BANDS,
    DemandInput,
    SubstituteBoardCandidateInput,
    SubstituteDemandInput,
    build_substitute_board_admission_plan,
    character_ngram_cosine_similarity,
    find_price_band_for_range,
    plan_new_demand_boards,
    select_substitute_board_candidate,
)
from moongcheap_ai.demand_constraints import (
    DemandConstraintParser,
    DemandRequirementResult,
    FacetConstraint,
    PreferenceGroup,
)


PROFILE_ORIGIN = "SYNTHETIC_HASH_NOT_PRODUCT_FACT"
PRICE_ORIGIN = "SYNTHETIC_CANONICAL_7_BAND_HASH"
SEMANTIC_TAGS = (
    "딸기맛",
    "초콜릿맛",
    "무향",
    "휴대하기 좋은",
    "부드러운 맛",
    "간편 섭취",
    "저자극",
)


CodeCanonicalizer = Callable[[str, str, int], int | tuple[int, object | None]]


def _stable_index(key: str, size: int) -> int:
    if size < 1:
        raise ValueError("stable index size must be positive")
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % size


def simulated_price_band(source_demand_id: str):
    """Regenerate one official seven-band choice independently of source price."""

    return PRICE_BANDS[_stable_index(f"price:{source_demand_id}", len(PRICE_BANDS))]


def _canonical_code(
    canonicalizer: CodeCanonicalizer | None,
    category_id: str,
    facet_name: str,
    value_code: int,
) -> int:
    if canonicalizer is None:
        return value_code
    result = canonicalizer(category_id, facet_name, value_code)
    return int(result[0] if isinstance(result, tuple) else result)


def _taxonomy_version(taxonomy: Mapping[str, Any]) -> str:
    version = taxonomy.get("taxonomy_version", taxonomy.get("version", ""))
    if not str(version).strip():
        raise ValueError("taxonomy version is missing")
    return str(version)


def build_synthetic_catalog_profiles(
    rows: Iterable[Mapping[str, str]],
    taxonomy: Mapping[str, Any],
    *,
    canonicalize_value_code: CodeCanonicalizer | None = None,
) -> dict[int, dict[str, Any]]:
    """Create catalog-level profiles without using any demand label or condition."""

    categories = {
        str(item["category_id"]): item
        for item in taxonomy.get("categories", ())
    }
    taxonomy_version = _taxonomy_version(taxonomy)
    catalog_contracts: dict[int, tuple[str, str]] = {}
    for row in rows:
        catalog_id = int(row["product_reference"])
        category_id = str(row["category_id"])
        requirement_taxonomy_version = str(
            row.get("taxonomy_version", taxonomy_version) or taxonomy_version
        )
        contract = (category_id, requirement_taxonomy_version)
        previous = catalog_contracts.setdefault(catalog_id, contract)
        if previous != contract:
            raise ValueError(
                f"catalog {catalog_id} has multiple category/taxonomy contracts: "
                f"{previous}, {contract}"
            )

    profiles: dict[int, dict[str, Any]] = {}
    for catalog_id, contract in sorted(catalog_contracts.items()):
        category_id, requirement_taxonomy_version = contract
        category = categories.get(category_id)
        if category is None:
            raise ValueError(f"category is absent from taxonomy: {category_id}")
        facet_values: dict[str, int] = {}
        facet_texts = []
        for facet in sorted(
            category.get("facets", ()),
            key=lambda item: int(item.get("order", 0)),
        ):
            facet_name = str(facet["name"])
            candidates = tuple(
                item
                for item in facet.get("values", ())
                if int(item["code"]) != 0
            )
            if not candidates:
                continue
            selected = candidates[
                _stable_index(
                    f"profile:{catalog_id}:{category_id}:{facet_name}",
                    len(candidates),
                )
            ]
            selected_code = _canonical_code(
                canonicalize_value_code,
                category_id,
                facet_name,
                int(selected["code"]),
            )
            canonical = next(
                (
                    item
                    for item in candidates
                    if int(item["code"]) == selected_code
                ),
                selected,
            )
            facet_values[facet_name] = selected_code
            facet_texts.append(str(canonical["value"]))

        semantic_tag = SEMANTIC_TAGS[
            _stable_index(f"semantic:{catalog_id}:{category_id}", len(SEMANTIC_TAGS))
        ]
        profiles[catalog_id] = {
            "catalogId": catalog_id,
            "catalogDisplayName": f"시뮬레이션 도감상품 {catalog_id}",
            "categoryId": category_id,
            # The v0.46 rows own the requirement-taxonomy contract.  A source
            # taxonomy artifact may carry a lifecycle suffix such as
            # ``v2.1-provisional`` even though its value codes are emitted as
            # ``v2.1`` by Part A.
            "taxonomyVersion": requirement_taxonomy_version,
            "taxonomyArtifactVersion": taxonomy_version,
            "facetValues": facet_values,
            "semanticText": " ".join((*facet_texts, semantic_tag)),
            "profileOrigin": PROFILE_ORIGIN,
        }
    return profiles


def _json_array(row: Mapping[str, str], name: str) -> list[Any]:
    raw = str(row.get(name, "") or "[]")
    value = json.loads(raw)
    if not isinstance(value, list):
        raise ValueError(f"{name} must contain a JSON array")
    return value


def _facet_constraint(value: Mapping[str, Any]) -> FacetConstraint:
    return FacetConstraint(
        facet_name=str(value["facet_name"]),
        value_code=int(value["value_code"]),
        value=str(value["value"]),
        constraint_type=str(value["constraint_type"]),
        evidence_clause=str(value.get("evidence_clause", value["value"])),
    )


def requirement_from_v046_row(row: Mapping[str, str]) -> DemandRequirementResult:
    """Deserialize only the stable v0.46 fields needed by board admission."""

    groups = tuple(
        PreferenceGroup(
            group_id=str(value["group_id"]),
            operator=str(value["operator"]),
            aggregation=str(value["aggregation"]),
            members=tuple(
                _facet_constraint(member) for member in value["members"]
            ),
        )
        for value in _json_array(row, "preference_groups")
    )
    semantic_field = (
        "semantic_preferences"
        if "semantic_preferences" in row
        else "free_text_preferences"
    )
    mode = str(
        row.get(
            "effective_requirement_mode",
            row.get("effective_constraint_mode", "NONE"),
        )
    )
    return DemandRequirementResult(
        status=str(row["constraint_status"]),
        constraints=tuple(
            _facet_constraint(value) for value in _json_array(row, "constraints")
        ),
        warnings=tuple(
            str(value) for value in _json_array(row, "constraint_warnings")
        ),
        clauses=tuple(
            str(value) for value in _json_array(row, "constraint_clauses")
        ),
        interpretation_method=str(row["constraint_interpretation_method"]),
        preference_groups=groups,
        semantic_preferences=tuple(
            str(value) for value in _json_array(row, semantic_field)
        ),
        diagnostic_code=str(row.get("constraint_diagnostic_code", "") or "") or None,
        effective_requirement_mode=mode,
    )


def _source_price_is_official(row: Mapping[str, str]) -> bool:
    try:
        lower = int(float(row["desired_price_min"]))
        upper_raw = str(row.get("desired_price_max", "") or "").strip()
        if not upper_raw:
            return False
        upper = int(float(upper_raw))
        find_price_band_for_range(lower, upper)
    except (KeyError, TypeError, ValueError):
        return False
    return True


def simulate_demand_board_handoff(
    source_rows: Iterable[Mapping[str, str]],
    taxonomy: Mapping[str, Any],
    *,
    as_of: datetime,
    min_participants: int,
    canonicalize_value_code: CodeCanonicalizer | None = None,
) -> dict[str, Any]:
    """Run new-board formation then alternative-board proposal mechanics."""

    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must include timezone information")
    rows = tuple(dict(row) for row in source_rows)
    if not rows:
        raise ValueError("source demand rows must not be empty")
    source_ids = [row["demand_id"] for row in rows]
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("duplicate source demand id")

    profiles = build_synthetic_catalog_profiles(
        rows,
        taxonomy,
        canonicalize_value_code=canonicalize_value_code,
    )
    taxonomy_version = _taxonomy_version(taxonomy)
    inputs: list[DemandInput] = []
    requirements: dict[int, DemandRequirementResult] = {}
    source_by_id: dict[int, dict[str, str]] = {}
    for demand_id, row in enumerate(rows, 1):
        band = simulated_price_band(row["demand_id"])
        source_by_id[demand_id] = row
        requirements[demand_id] = requirement_from_v046_row(row)
        inputs.append(DemandInput(
            id=demand_id,
            catalog_id=int(row["product_reference"]),
            created_at=as_of - timedelta(hours=1),
            updated_at=as_of,
            desired_price_min=band.lower_bound,
            desired_price_max=band.upper_bound,
            quantity=int(row["quantity"]),
            is_substitutable=str(row["is_substitutable"]).casefold() == "true",
            status="UNASSIGNED",
            label=str(row["label"]),
            desire_end_at=as_of + timedelta(days=7),
            processed_at=as_of,
        ))

    new_board_plans = plan_new_demand_boards(
        inputs,
        as_of=as_of,
        min_participants=min_participants,
    )
    board_rows = []
    board_candidates = []
    direct_board_by_demand: dict[int, int] = {}
    for offset, plan in enumerate(new_board_plans, 1):
        board_id = 1_000_000 + offset
        profile = profiles[plan.catalog_id]
        for demand_id in plan.demand_ids:
            direct_board_by_demand[demand_id] = board_id
        candidate = SubstituteBoardCandidateInput(
            id=board_id,
            catalog_id=plan.catalog_id,
            category_id=profile["categoryId"],
            taxonomy_version=profile["taxonomyVersion"],
            price_min=plan.price_min,
            price_max=plan.price_max,
            participant_count=plan.participant_count,
            facet_values=profile["facetValues"],
            sale_end_at=as_of + timedelta(days=5),
            status="GB_GATHERING",
            semantic_text=profile["semanticText"],
        )
        board_candidates.append(candidate)
        board_rows.append({
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
            "saleEndAt": (as_of + timedelta(days=5)).isoformat(),
            "directDemandIds": list(plan.demand_ids),
            "pendingSubstituteDemandIds": [],
            "facetValues": profile["facetValues"],
            "semanticText": profile["semanticText"],
            "profileOrigin": PROFILE_ORIGIN,
        })

    admission_items = []
    unassigned_inputs = [
        item for item in inputs if item.id not in direct_board_by_demand
    ]
    for item in unassigned_inputs:
        row = source_by_id[item.id]
        current = SubstituteDemandInput.from_demand(
            item,
            category_id=row["category_id"],
            taxonomy_version=row.get("taxonomy_version", taxonomy_version),
            requirement=requirements[item.id],
        )
        decision = select_substitute_board_candidate(
            current,
            board_candidates,
            as_of=as_of,
            canonicalize_value_code=canonicalize_value_code,
            text_similarity_scorer=character_ngram_cosine_similarity,
        )
        admission_items.append((current, decision))

    admission_plan = build_substitute_board_admission_plan(
        admission_items,
        batch_id=f"simulated-board-handoff-{as_of.date().isoformat()}",
        planned_at=as_of,
        rule_version="requirement-v0.46+board-formation-v0.1+admission-v0.1",
        text_scorer_version="character-bigram-cosine-fixture-only",
    )
    proposal_by_demand = {
        int(item["demandId"]): item for item in admission_plan["proposals"]
    }
    not_eligible_by_demand = {
        int(item["demandId"]): item for item in admission_plan["notEligible"]
    }
    unmatched_by_demand = {
        int(item["demandId"]): item for item in admission_plan["unmatched"]
    }
    board_output_by_id = {
        int(item["demandBoardId"]): item for item in board_rows
    }
    for proposal in admission_plan["proposals"]:
        board_output = board_output_by_id[int(proposal["demandBoardId"])]
        board_output["pendingSubstituteDemandIds"].append(proposal["demandId"])
    for board_output in board_rows:
        board_output["pendingSubstituteOfferCount"] = len(
            board_output["pendingSubstituteDemandIds"]
        )

    demand_states = []
    for item in inputs:
        row = source_by_id[item.id]
        band = simulated_price_band(row["demand_id"])
        if item.id in direct_board_by_demand:
            state = "ASSIGNED"
            assignment_type = "ORIGINAL_CATALOG"
            board_id: int | None = direct_board_by_demand[item.id]
            reason_codes: list[str] = []
        elif item.id in proposal_by_demand:
            proposal = proposal_by_demand[item.id]
            state = "SUBSTITUTE_OFFERED"
            assignment_type = "SUBSTITUTE_PROPOSAL"
            board_id = int(proposal["demandBoardId"])
            reason_codes = []
        elif item.id in not_eligible_by_demand:
            state = "UNASSIGNED"
            assignment_type = "NONE"
            board_id = None
            reason_codes = list(not_eligible_by_demand[item.id]["reasonCodes"])
        else:
            state = "UNASSIGNED"
            assignment_type = "NONE"
            board_id = None
            reason_codes = list(unmatched_by_demand[item.id]["reasonCodes"])
        demand_states.append({
            "demandId": item.id,
            "sourceDemandId": row["demand_id"],
            "originalCatalogId": item.catalog_id,
            "categoryId": row["category_id"],
            "status": state,
            "assignmentType": assignment_type,
            "demandBoardId": board_id,
            "quantity": item.quantity,
            "isSubstitutable": item.is_substitutable,
            "requirementStatus": requirements[item.id].status,
            "effectiveRequirementMode": (
                requirements[item.id].effective_requirement_mode
            ),
            "sourceDesiredPriceMin": row.get("desired_price_min", ""),
            "sourceDesiredPriceMax": row.get("desired_price_max", ""),
            "desiredPriceMin": band.lower_bound,
            "desiredPriceMax": band.upper_bound,
            "priceOrigin": PRICE_ORIGIN,
            "reasonCodes": reason_codes,
        })

    mode_counts = Counter(
        value.effective_requirement_mode for value in requirements.values()
    )
    status_counts = Counter(value.status for value in requirements.values())
    return {
        "schemaVersion": "part-c-demand-board-simulation.v0.1",
        "dataClassification": "SYNTHETIC_MECHANICS_ONLY_NOT_PRODUCT_FACT",
        "generatedAt": as_of.isoformat(),
        "consumerNotice": (
            "Part C may use this to exercise board/seller matching mechanics. "
            "Catalog facets, semantic text, and regenerated prices are synthetic."
        ),
        "simulationPolicy": {
            "minParticipants": min_participants,
            "priceOrigin": PRICE_ORIGIN,
            "catalogProfileOrigin": PROFILE_ORIGIN,
            "priceRule": "official seven bands selected by stable demand-id hash",
            "profileRule": "one taxonomy value per facet selected by stable catalog-id hash",
            "substituteConfirmation": "not simulated; proposals remain SUBSTITUTE_OFFERED",
            "participantCountIncludesPendingOffers": False,
            "sellerDataIncluded": False,
        },
        "summary": {
            "sourceDemandCount": len(inputs),
            "catalogProfileCount": len(profiles),
            "sourcePriceContractViolationCount": sum(
                not _source_price_is_official(row) for row in rows
            ),
            "demandBoardCount": len(board_rows),
            "directAssignedDemandCount": len(direct_board_by_demand),
            "substituteProposalCount": len(admission_plan["proposals"]),
            "substitutionNotEligibleCount": len(admission_plan["notEligible"]),
            "unmatchedDemandCount": len(admission_plan["unmatched"]),
            "reviewQueueCount": 0,
            "requirementStatusCounts": dict(sorted(status_counts.items())),
            "effectiveRequirementModeCounts": dict(sorted(mode_counts.items())),
        },
        "catalogProfiles": list(profiles.values()),
        "demandBoards": board_rows,
        "substituteAdmissionPlan": admission_plan,
        "demandStates": demand_states,
    }


def build_part_c_board_snapshot(simulation: Mapping[str, Any]) -> dict[str, Any]:
    """Remove demand-level diagnostics from the seller-matching handoff."""

    return {
        "schemaVersion": "part-c-demand-board-snapshot.v0.1",
        "dataClassification": simulation["dataClassification"],
        "generatedAt": simulation["generatedAt"],
        "consumerNotice": simulation["consumerNotice"],
        "sourceSummary": simulation["summary"],
        "simulationPolicy": simulation["simulationPolicy"],
        "demandBoards": simulation["demandBoards"],
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a synthetic 5k demand-board handoff for Part C"
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--taxonomy", type=Path, required=True)
    parser.add_argument("--rules", type=Path, default=Path("config/demand_constraint_rules.json"))
    parser.add_argument("--aliases", type=Path, default=Path("config/demand_constraint_aliases.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--board-output",
        type=Path,
        help="Optional compact demand-board-only JSON for Part C",
    )
    parser.add_argument("--as-of", default="2026-09-05T00:00:00+00:00")
    parser.add_argument("--min-participants", type=int, default=5)
    parser.add_argument(
        "--allow-synthetic-catalog-profiles",
        action="store_true",
        help="Required acknowledgement that generated profiles are not product facts",
    )
    args = parser.parse_args()
    if not args.allow_synthetic_catalog_profiles:
        parser.error("--allow-synthetic-catalog-profiles is required")

    taxonomy = json.loads(args.taxonomy.read_text(encoding="utf-8"))
    requirement_parser = DemandConstraintParser.from_taxonomy(
        taxonomy,
        rules_path=args.rules,
        aliases_path=args.aliases,
    )
    with args.input.open(encoding="utf-8-sig", newline="") as source:
        rows = tuple(csv.DictReader(source))
    as_of = datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))
    output = simulate_demand_board_handoff(
        rows,
        taxonomy,
        as_of=as_of,
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
                build_part_c_board_snapshot(output),
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    print(json.dumps({
        "output": str(args.output),
        "boardOutput": (
            str(args.board_output) if args.board_output is not None else None
        ),
        **output["summary"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
