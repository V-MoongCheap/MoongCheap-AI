from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from moongcheap_ai.demand_clustering import (
    SubstituteBoardCandidateInput,
    SubstituteDemandInput,
    select_substitute_board_candidate,
)
from moongcheap_ai.demand_constraints import DemandConstraintParser
from scripts.demand.simulate_demand_board_handoff import requirement_from_v046_row


def _fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_strings(value: object) -> tuple[str, ...]:
    parsed = json.loads(str(value) or "[]")
    if not isinstance(parsed, list):
        raise ValueError("profile evidence fields must contain JSON arrays")
    return tuple(str(item).strip() for item in parsed if str(item).strip())


def build_actual_proposal_review_set(
    simulation: dict[str, Any],
    source_rows: tuple[dict[str, str], ...],
    profiles: pd.DataFrame,
    *,
    canonicalize_value_code,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Build one blinded Judge row per actual board proposal."""

    required_profile_columns = {
        "source_product_id",
        "product_name",
        "service_category_id",
        "product_form",
        "functional_ingredients_json",
        "main_functionality_claim_ids_json",
        "main_functionality_claim_texts_json",
        "intake_method_text",
    }
    if missing := sorted(required_profile_columns - set(profiles.columns)):
        raise ValueError("profiles missing columns: " + ", ".join(missing))
    normalized = profiles.fillna("").copy()
    normalized["source_product_id"] = normalized["source_product_id"].astype(str)
    if normalized["source_product_id"].duplicated().any():
        raise ValueError("profile source product IDs must be unique")
    profile_by_id = normalized.set_index("source_product_id")

    row_by_source_id = {str(row["demand_id"]): row for row in source_rows}
    if len(row_by_source_id) != len(source_rows):
        raise ValueError("source demand IDs must be unique")
    state_by_id = {
        int(state["demandId"]): state
        for state in simulation["demandStates"]
    }
    board_by_id = {
        int(board["demandBoardId"]): board
        for board in simulation["demandBoards"]
    }
    proposals = simulation["substituteAdmissionPlan"]["proposals"]
    proposal_demand_ids = [int(item["demandId"]) for item in proposals]
    if len(proposal_demand_ids) != len(set(proposal_demand_ids)):
        raise ValueError("a demand has multiple actual proposals")

    output_rows: list[dict[str, Any]] = []
    violation_counts: Counter[str] = Counter()
    for proposal in proposals:
        demand_id = int(proposal["demandId"])
        source_id = str(proposal["originalCatalogId"])
        candidate_id = str(proposal["substituteCatalogId"])
        board_id = int(proposal["demandBoardId"])
        state = state_by_id[demand_id]
        board = board_by_id[board_id]
        source_row = row_by_source_id[str(state["sourceDemandId"])]
        source = profile_by_id.loc[source_id]
        candidate = profile_by_id.loc[candidate_id]
        requirement = requirement_from_v046_row(source_row)
        offered_at = datetime.fromisoformat(proposal["offeredAt"])
        violations: list[str] = []

        def require(condition: bool, code: str) -> None:
            if not condition:
                violations.append(code)

        require(bool(state["isSubstitutable"]), "NONCONSENTING_DEMAND")
        require(state["status"] == "SUBSTITUTE_OFFERED", "WRONG_FINAL_STATUS")
        require(source_id != candidate_id, "SAME_CATALOG_PROPOSAL")
        require(int(board["catalogId"]) == int(candidate_id), "BOARD_CATALOG_MISMATCH")
        require(int(board["priceMax"]) <= int(state["desiredPriceMax"]), "PRICE_VIOLATION")
        require(proposal["requiresUserConfirmation"] is True, "CONFIRMATION_BYPASSED")
        require(int(proposal["participantCountDeltaOnProposal"]) == 0, "COUNT_CHANGED_ON_PROPOSAL")
        require(int(proposal["participantCountDeltaOnAccept"]) == 1, "WRONG_ACCEPT_COUNT_DELTA")
        require(proposal["onAcceptStatus"] == "ASSIGNED", "WRONG_ACCEPT_STATUS")
        require(proposal["onRejectStatus"] == "UNASSIGNED", "WRONG_REJECT_STATUS")

        source_claim_ids = set(_json_strings(
            source["main_functionality_claim_ids_json"]
        ))
        candidate_claim_ids = set(_json_strings(
            candidate["main_functionality_claim_ids_json"]
        ))
        require(bool(source_claim_ids), "SOURCE_FUNCTION_EVIDENCE_EMPTY")
        require(
            source_claim_ids.issubset(candidate_claim_ids),
            "IDENTITY_FUNCTION_COVERAGE_VIOLATION",
        )
        require(
            str(source["service_category_id"])
            == str(candidate["service_category_id"])
            == str(board["categoryId"]),
            "CATEGORY_MISMATCH",
        )

        audit_demand = SubstituteDemandInput(
            id=demand_id,
            catalog_id=int(source_id),
            category_id=str(board["categoryId"]),
            taxonomy_version=str(board["taxonomyVersion"]),
            desired_price_min=int(state["desiredPriceMin"]),
            desired_price_max=int(state["desiredPriceMax"]),
            quantity=int(state["quantity"]),
            is_substitutable=True,
            requirement=requirement,
            status="UNASSIGNED",
            desire_end_at=offered_at + timedelta(days=1),
        )
        audit_board = SubstituteBoardCandidateInput(
            id=board_id,
            catalog_id=int(candidate_id),
            category_id=str(board["categoryId"]),
            taxonomy_version=str(board["taxonomyVersion"]),
            price_min=int(board["priceMin"]),
            price_max=int(board["priceMax"]),
            participant_count=int(board["participantCount"]),
            facet_values=board["facetValues"],
            sale_end_at=datetime.fromisoformat(board["saleEndAt"]),
            status=str(board["status"]),
            semantic_text=str(board["semanticText"]),
        )
        hard_gate_replay = select_substitute_board_candidate(
            audit_demand,
            (audit_board,),
            as_of=offered_at,
            canonicalize_value_code=canonicalize_value_code,
            text_similarity_scorer=lambda _left, _right: 0.5,
        )
        require(
            hard_gate_replay.selected_board is not None,
            "BOARD_REQUIREMENT_HARD_GATE_VIOLATION",
        )

        violation_counts.update(violations)
        output_rows.append({
            "proposal_id": f"demand-{demand_id}",
            "demand_id": demand_id,
            "pair_id": f"{source_id}__TO__{candidate_id}",
            "source_catalog_id": source_id,
            "candidate_catalog_id": candidate_id,
            "demand_board_id": board_id,
            "service_category_id": str(source["service_category_id"]),
            "source_product_name": str(source["product_name"]),
            "candidate_product_name": str(candidate["product_name"]),
            "source_product_form": str(source["product_form"]),
            "candidate_product_form": str(candidate["product_form"]),
            "source_functional_ingredients": " | ".join(_json_strings(
                source["functional_ingredients_json"]
            )),
            "candidate_functional_ingredients": " | ".join(_json_strings(
                candidate["functional_ingredients_json"]
            )),
            "source_functionality": " | ".join(_json_strings(
                source["main_functionality_claim_texts_json"]
            )),
            "candidate_functionality": " | ".join(_json_strings(
                candidate["main_functionality_claim_texts_json"]
            )),
            "source_intake_method": str(source["intake_method_text"]),
            "candidate_intake_method": str(candidate["intake_method_text"]),
            "requirement_status": str(proposal["requirementStatus"]),
            "effective_requirement_mode": str(
                proposal["effectiveRequirementMode"]
            ),
            "extra_requirement": str(source_row.get("extra_requirement", "")),
            "automatic_contract_status": "PASSED" if not violations else "FAILED",
            "automatic_violation_codes": "|".join(violations),
        })

    review = pd.DataFrame(output_rows)
    summary = {
        "schemaVersion": "actual-board-proposal-review-set.v1",
        "proposalCount": len(review),
        "uniquePairCount": int(review["pair_id"].nunique()),
        "automaticContractPassedCount": int(
            review["automatic_contract_status"].eq("PASSED").sum()
        ),
        "automaticContractFailedCount": int(
            review["automatic_contract_status"].eq("FAILED").sum()
        ),
        "automaticViolationCounts": dict(sorted(violation_counts.items())),
        "requirementModeCounts": {
            str(key): int(value)
            for key, value in review[
                "effective_requirement_mode"
            ].value_counts().sort_index().items()
        },
        "judgeLeakagePolicy": (
            "The LLM prompt receives grounded product facts only; E5 scores, "
            "hard-gate outcomes, automatic audit results, and demand conditions "
            "are excluded from the prompt."
        ),
    }
    return review, summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a blind review set from actual board proposals"
    )
    parser.add_argument(
        "--simulation",
        type=Path,
        default=Path(
            "../demand-board-simulation-artifacts/"
            "part_c_demand_board_simulation_5000_clustering_scope.json"
        ),
    )
    parser.add_argument(
        "--demands",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--profiles",
        type=Path,
        default=Path(
            "data/reports/grounded_catalog_substitution_evidence_v2/"
            "catalog_profile_candidates.csv"
        ),
    )
    parser.add_argument(
        "--taxonomy",
        type=Path,
        required=True,
    )
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
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("../actual-board-proposal-review-set"),
    )
    args = parser.parse_args()
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise RuntimeError("output directory is not empty")

    simulation = json.loads(args.simulation.read_text(encoding="utf-8"))
    with args.demands.open(encoding="utf-8-sig", newline="") as source:
        rows = tuple(dict(row) for row in csv.DictReader(source))
    taxonomy = json.loads(args.taxonomy.read_text(encoding="utf-8"))
    constraint_parser = DemandConstraintParser.from_taxonomy(
        taxonomy,
        rules_path=args.rules,
        aliases_path=args.aliases,
    )
    review, summary = build_actual_proposal_review_set(
        simulation,
        rows,
        pd.read_csv(args.profiles, dtype=str, keep_default_na=False),
        canonicalize_value_code=constraint_parser.canonicalize_value_code,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    review_path = args.output_dir / "actual_proposal_review_set.csv"
    review.to_csv(review_path, index=False, encoding="utf-8-sig")
    manifest = {
        **summary,
        "createdAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sourceArtifacts": {
            "simulationPath": str(args.simulation),
            "simulationSha256": _fingerprint(args.simulation),
            "demandsPath": str(args.demands),
            "demandsSha256": _fingerprint(args.demands),
            "profilesPath": str(args.profiles),
            "profilesSha256": _fingerprint(args.profiles),
            "taxonomyPath": str(args.taxonomy),
            "taxonomySha256": _fingerprint(args.taxonomy),
        },
        "reviewSetFile": review_path.name,
    }
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()
