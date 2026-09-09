"""Create the v0.4 Part C board snapshot with grounded function evidence.

Registration times and seven-band prices remain explicit deterministic
simulation inputs because the Part A fixture does not contain service event
times or contract-compatible price bands. Product names, functions,
ingredients, forms, and intake evidence come from the MFDS-grounded profile
artifact. Catalog eligibility is assumed to have been decided upstream and is
never inferred from MFDS product names or record types. Unapproved directional
relations are disabled.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from moongcheap_ai.demand_clustering import character_ngram_cosine_similarity
from moongcheap_ai.demand_clustering.function_relation_embedding import (
    load_sentence_transformer,
    sentence_transformer_embeddings,
)
from moongcheap_ai.demand_clustering.profile_contract import (
    SUBSTITUTION_EVIDENCE_READY_STATUSES,
)
from moongcheap_ai.demand_constraints import DemandConstraintParser
from scripts.demand.simulate_demand_board_handoff import (
    CodeCanonicalizer,
    _sha256,
    requirement_from_v046_row,
)
from scripts.demand.simulate_hourly_demand_board_handoff import (
    DEFAULT_ARRIVAL_HOURS,
    DEFAULT_BATCH_INTERVAL_MINUTES,
    build_part_c_hourly_board_snapshot,
    simulate_hourly_demand_board_handoff,
)


PROFILE_ORIGIN = "MFDS_I0030_I2710_FUNCTION_EVIDENCE"
DATA_CLASSIFICATION = (
    "SYNTHETIC_TIMING_AND_PRICE_WITH_GROUNDED_PRODUCT_EVIDENCE"
)
SIMULATION_SCHEMA = "part-c-demand-board-hourly-simulation.v0.4"
SNAPSHOT_SCHEMA = "part-c-demand-board-snapshot.v0.4"
RULE_VERSION = (
    "requirement-v0.46+hourly-board-formation-v0.4+"
    "identity-only-product-gate-v1+admission-v0.1"
)
TEXT_SCORER_VERSION = "multilingual-e5-small-preference-ranker.v0.4"


def _normalized_text(value: object) -> str:
    return re.sub(
        r"\s+",
        "",
        unicodedata.normalize("NFKC", str(value)).casefold(),
    )


def _json_strings(value: object) -> tuple[str, ...]:
    parsed = json.loads(str(value) or "[]")
    if not isinstance(parsed, list):
        raise ValueError("grounded profile JSON fields must contain arrays")
    return tuple(str(item).strip() for item in parsed if str(item).strip())


def _taxonomy_value_indexes(
    taxonomy: Mapping[str, Any],
) -> dict[str, dict[str, dict[str, int]]]:
    indexes: dict[str, dict[str, dict[str, int]]] = {}
    for category in taxonomy.get("categories", ()):
        category_id = str(category["category_id"])
        indexes[category_id] = {}
        for facet in category.get("facets", ()):
            values: dict[str, int] = {}
            for value in facet.get("values", ()):
                code = int(value["code"])
                if code == 0:
                    continue
                normalized = _normalized_text(value["value"])
                values[normalized] = min(code, values.get(normalized, code))
            indexes[category_id][str(facet["name"])] = values
    return indexes


def _mapped_facet_values(
    profile: Mapping[str, Any],
    category_indexes: Mapping[str, Mapping[str, int]],
) -> dict[str, int]:
    mapped: dict[str, int] = {}
    form = _normalized_text(profile["product_form"])
    if form and form in category_indexes.get("product_form", {}):
        mapped["product_form"] = category_indexes["product_form"][form]

    ingredients = _json_strings(profile["functional_ingredients_json"])
    joined_ingredients = _normalized_text(", ".join(ingredients))
    if (
        joined_ingredients
        and joined_ingredients
        in category_indexes.get("functional_ingredients", {})
    ):
        mapped["functional_ingredients"] = category_indexes[
            "functional_ingredients"
        ][joined_ingredients]

    intake = _normalized_text(profile["intake_method_text"])
    frequency_matches = [
        (len(value), code)
        for value, code in category_indexes.get("daily_frequency", {}).items()
        if value and value in intake
    ]
    if frequency_matches:
        mapped["daily_frequency"] = max(frequency_matches)[1]
    return mapped


def build_grounded_catalog_board_profiles(
    source_rows: Iterable[Mapping[str, str]],
    taxonomy: Mapping[str, Any],
    grounded_profiles: pd.DataFrame,
) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    """Join every fixture product to its MFDS-grounded immutable evidence."""

    required_columns = {
        "source_product_id",
        "product_name",
        "service_category_id",
        "taxonomy_version",
        "record_type",
        "product_form",
        "functional_ingredients_json",
        "main_functionality_claim_texts_json",
        "intake_method_text",
        "profile_status",
        "profile_reason_codes",
    }
    if missing := sorted(required_columns - set(grounded_profiles.columns)):
        raise ValueError("grounded profiles missing columns: " + ", ".join(missing))
    source_contracts: dict[int, tuple[str, str]] = {}
    for row in source_rows:
        catalog_id = int(row["product_reference"])
        contract = (str(row["category_id"]), str(row["taxonomy_version"]))
        previous = source_contracts.setdefault(catalog_id, contract)
        if previous != contract:
            raise ValueError(f"catalog {catalog_id} has inconsistent demand contracts")

    normalized = grounded_profiles.fillna("").copy()
    normalized["source_product_id"] = normalized["source_product_id"].astype(str)
    if normalized["source_product_id"].duplicated().any():
        raise ValueError("grounded source product IDs must be unique")
    by_source = normalized.set_index("source_product_id")
    missing_products = sorted(
        str(catalog_id)
        for catalog_id in source_contracts
        if str(catalog_id) not in by_source.index
    )
    if missing_products:
        raise ValueError(
            "grounded profiles missing fixture products: "
            + ", ".join(missing_products)
        )

    indexes = _taxonomy_value_indexes(taxonomy)
    profiles: dict[int, dict[str, Any]] = {}
    facet_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    for catalog_id, (category_id, taxonomy_version) in sorted(
        source_contracts.items()
    ):
        profile = by_source.loc[str(catalog_id)]
        if str(profile["service_category_id"]) != category_id:
            raise ValueError(f"catalog {catalog_id} category does not match Part A")
        if str(profile["taxonomy_version"]) != taxonomy_version:
            raise ValueError(f"catalog {catalog_id} taxonomy does not match Part A")
        if category_id not in indexes:
            raise ValueError(f"taxonomy is missing category: {category_id}")
        facets = _mapped_facet_values(profile, indexes[category_id])
        facet_counts.update(facets.keys())
        status = str(profile["profile_status"])
        status_counts[status] += 1
        ingredients = _json_strings(profile["functional_ingredients_json"])
        functions = _json_strings(profile["main_functionality_claim_texts_json"])
        semantic_text = "\n".join((
            f"상품명: {profile['product_name']}",
            f"서비스 카테고리: {category_id}",
            f"제품 형태: {profile['product_form']}",
            "기능성 원료: " + ", ".join(ingredients),
            "공인 기능: " + ", ".join(functions),
            f"섭취 방법: {profile['intake_method_text']}",
        ))
        profiles[catalog_id] = {
            "catalogId": catalog_id,
            "catalogDisplayName": str(profile["product_name"]),
            "categoryId": category_id,
            "taxonomyVersion": taxonomy_version,
            "facetValues": facets,
            "semanticText": semantic_text,
            "profileOrigin": PROFILE_ORIGIN,
            "substitutionEvidenceStatus": status,
            "recordType": str(profile["record_type"]),
            "substitutionEvidenceReasonCodes": str(
                profile["profile_reason_codes"]
            ),
        }
    return profiles, {
        "profileCount": len(profiles),
        "profileStatusCounts": dict(sorted(status_counts.items())),
        "mappedFacetCounts": dict(sorted(facet_counts.items())),
    }


def build_identity_only_bounded_candidates(
    grounded_profiles: pd.DataFrame,
    top_candidates: pd.DataFrame,
    *,
    primary_limit: int = 10,
    fallback_limit: int = 20,
) -> tuple[dict[int, frozenset[int]], dict[int, tuple[str, ...]], dict[str, Any]]:
    """Apply the fixed E5 window while disabling every unapproved relation."""

    if primary_limit <= 0 or fallback_limit < primary_limit:
        raise ValueError("invalid bounded retrieval limits")
    required = {
        "source_catalog_id",
        "candidate_catalog_id",
        "rank",
        "hard_gate_eligible",
        "coverage_mode",
    }
    if missing := sorted(required - set(top_candidates.columns)):
        raise ValueError("top candidates missing columns: " + ", ".join(missing))
    profile_status = {
        int(row.source_product_id): str(row.profile_status)
        for row in grounded_profiles.itertuples(index=False)
    }

    ranked = top_candidates.copy()
    ranked["source_product_id"] = ranked["source_catalog_id"].map(
        lambda value: int(str(value).removeprefix("catalog-seed-"))
    )
    ranked["candidate_product_id"] = ranked["candidate_catalog_id"].map(
        lambda value: int(str(value).removeprefix("catalog-seed-"))
    )
    ranked["rank"] = pd.to_numeric(ranked["rank"], errors="raise").astype(int)
    ranked["eligible"] = ranked["hard_gate_eligible"].map(
        lambda value: value is True or str(value).strip().casefold() in {"true", "1"}
    )
    identity = ranked.loc[
        ranked["eligible"]
        & ranked["coverage_mode"].eq("IDENTITY_ONLY")
        & ranked["rank"].le(fallback_limit)
    ].copy()

    allowed: dict[int, frozenset[int]] = {}
    fallback_sources = 0
    for source_id, group in identity.groupby("source_product_id", sort=True):
        primary = group.loc[group["rank"].le(primary_limit)]
        selected = primary if not primary.empty else group
        if primary.empty:
            fallback_sources += 1
        candidate_ids = frozenset(selected["candidate_product_id"].astype(int))
        if candidate_ids:
            if profile_status.get(int(source_id)) not in (
                SUBSTITUTION_EVIDENCE_READY_STATUSES
            ):
                raise ValueError("retrieval source lacks function evidence")
            if any(
                profile_status.get(value)
                not in SUBSTITUTION_EVIDENCE_READY_STATUSES
                for value in candidate_ids
            ):
                raise ValueError("retrieval candidate lacks function evidence")
            allowed[int(source_id)] = candidate_ids

    reasons: dict[int, tuple[str, ...]] = {}
    for catalog_id, status in profile_status.items():
        if status not in SUBSTITUTION_EVIDENCE_READY_STATUSES:
            reasons[catalog_id] = (
                f"SOURCE_FUNCTION_EVIDENCE_NOT_READY:{status}",
            )
        elif catalog_id not in allowed:
            reasons[catalog_id] = (
                "NO_IDENTITY_COVERAGE_CANDIDATE_IN_TOP20",
            )
    relation_rows = ranked.loc[
        ranked["eligible"] & ranked["coverage_mode"].eq("RELATION_ASSISTED")
    ]
    return allowed, reasons, {
        "sourceProfileCount": len(profile_status),
        "functionEvidenceReadySourceCount": sum(
            status in SUBSTITUTION_EVIDENCE_READY_STATUSES
            for status in profile_status.values()
        ),
        "identityEligibleSourceCount": len(allowed),
        "identityEligibleDirectedPairCount": sum(map(len, allowed.values())),
        "primaryWindowSourceCount": len(allowed) - fallback_sources,
        "fallbackWindowSourceCount": fallback_sources,
        "relationAssistedRowsDisabled": len(relation_rows),
        "relationDeploymentStatus": "REQUIRES_DOMAIN_OWNER_SIGNOFF",
        "runtimeRelationPolicy": "IDENTITY_ONLY",
    }


def build_e5_preference_scorer(
    model_path: Path,
    query_texts: Iterable[str],
    passage_texts: Iterable[str],
    *,
    batch_size: int,
) -> Callable[[str, str], float]:
    """Precompute an optional CPU E5 rank signal; it is never a hard gate."""

    queries = sorted({str(value) for value in query_texts if str(value).strip()})
    passages = sorted({str(value) for value in passage_texts if str(value).strip()})
    if not queries or not passages:
        return character_ngram_cosine_similarity
    model = load_sentence_transformer(str(model_path), None)
    query_vectors = sentence_transformer_embeddings(
        model,
        queries,
        prefix="query: ",
        batch_size=batch_size,
    )
    passage_vectors = sentence_transformer_embeddings(
        model,
        passages,
        prefix="passage: ",
        batch_size=batch_size,
    )
    query_by_text = dict(zip(queries, query_vectors, strict=True))
    passage_by_text = dict(zip(passages, passage_vectors, strict=True))

    def score(left: str, right: str) -> float:
        cosine = float(np.dot(query_by_text[left], passage_by_text[right]))
        return round(max(0.0, min(1.0, (cosine + 1.0) / 2.0)), 6)

    return score


def validate_grounded_hourly_simulation(
    simulation: Mapping[str, Any],
    allowed_candidates: Mapping[int, frozenset[int]],
) -> dict[str, Any]:
    """Fail the artifact build if any cross-layer state invariant is broken."""

    summary = simulation["summary"]
    states = simulation["demandStates"]
    boards = simulation["demandBoards"]
    proposals = simulation["substituteAdmissionPlan"]["proposals"]
    if sum(summary["finalDemandStatusCounts"].values()) != len(states):
        raise ValueError("final demand states do not add up")
    if len(states) != summary["sourceDemandCount"]:
        raise ValueError("source demand count does not match demand states")
    proposal_ids = [int(item["demandId"]) for item in proposals]
    if len(proposal_ids) != len(set(proposal_ids)):
        raise ValueError("a demand received more than one substitute proposal")
    state_by_id = {int(item["demandId"]): item for item in states}
    board_by_id = {int(item["demandBoardId"]): item for item in boards}
    for proposal in proposals:
        demand_id = int(proposal["demandId"])
        source_id = int(proposal["originalCatalogId"])
        candidate_id = int(proposal["substituteCatalogId"])
        board_id = int(proposal["demandBoardId"])
        state = state_by_id[demand_id]
        board = board_by_id[board_id]
        if not state["isSubstitutable"]:
            raise ValueError("non-consenting demand received a proposal")
        if candidate_id not in allowed_candidates.get(source_id, frozenset()):
            raise ValueError("proposal bypassed the identity-only product gate")
        if source_id == candidate_id or board["catalogId"] != candidate_id:
            raise ValueError("proposal catalog/board identity is inconsistent")
        if int(board["priceMax"]) > int(state["desiredPriceMax"]):
            raise ValueError("proposal bypassed the board price gate")
        if state["status"] != "SUBSTITUTE_OFFERED":
            raise ValueError("proposal demand is not awaiting user confirmation")

    direct_ids = [
        int(demand_id)
        for board in boards
        for demand_id in board["directDemandIds"]
    ]
    pending_ids = [
        int(demand_id)
        for board in boards
        for demand_id in board["pendingSubstituteDemandIds"]
    ]
    if len(direct_ids) != len(set(direct_ids)):
        raise ValueError("direct demand appears in multiple boards")
    if set(direct_ids) & set(pending_ids):
        raise ValueError("pending substitute offer was counted as a participant")
    if sorted(pending_ids) != sorted(proposal_ids):
        raise ValueError("board pending offers do not match proposals")
    if sum(int(board["participantCount"]) for board in boards) != len(direct_ids):
        raise ValueError("confirmed board participants do not match direct demands")
    state_contract = simulation["substituteAdmissionPlan"]["stateContract"]
    if state_contract != {
        "proposal": "UNASSIGNED_TO_SUBSTITUTE_OFFERED",
        "accept": "SUBSTITUTE_OFFERED_TO_ASSIGNED",
        "reject": "SUBSTITUTE_OFFERED_TO_UNASSIGNED",
        "proposalIncrementsParticipantCount": False,
    }:
        raise ValueError("simulation state contract differs from Backend")
    if summary["reviewQueueCount"] != 0:
        raise ValueError("runtime review rows are forbidden")
    return {
        "status": "PASSED",
        "sourceDemandCountChecked": len(states),
        "proposalCountChecked": len(proposals),
        "boardCountChecked": len(boards),
        "runtimeReviewRows": 0,
        "participantCountIncludesPendingOffers": False,
        "relationAssistedProposalCount": 0,
    }


def simulate_grounded_hourly_demand_board_handoff(
    source_rows: Iterable[Mapping[str, str]],
    taxonomy: Mapping[str, Any],
    grounded_profiles: pd.DataFrame,
    top_candidates: pd.DataFrame,
    *,
    start_at: datetime,
    arrival_window: timedelta,
    batch_interval: timedelta,
    min_participants: int,
    canonicalize_value_code: CodeCanonicalizer | None = None,
    text_similarity_scorer: Callable[[str, str], float] | None = None,
) -> dict[str, Any]:
    rows = tuple(dict(row) for row in source_rows)
    catalog_profiles, profile_summary = build_grounded_catalog_board_profiles(
        rows,
        taxonomy,
        grounded_profiles,
    )
    allowed, gate_reasons, retrieval_summary = (
        build_identity_only_bounded_candidates(
            grounded_profiles,
            top_candidates,
        )
    )
    output = simulate_hourly_demand_board_handoff(
        rows,
        taxonomy,
        start_at=start_at,
        arrival_window=arrival_window,
        batch_interval=batch_interval,
        min_participants=min_participants,
        canonicalize_value_code=canonicalize_value_code,
        catalog_profiles=catalog_profiles,
        eligible_substitute_catalog_ids=allowed,
        product_gate_reasons=gate_reasons,
        text_similarity_scorer=text_similarity_scorer,
    )
    output["schemaVersion"] = SIMULATION_SCHEMA
    output["dataClassification"] = DATA_CLASSIFICATION
    output["consumerNotice"] = (
        "Part C may use this snapshot to exercise demand-board/seller matching. "
        "Catalog IDs are assumed to be upstream-authorized inputs. MFDS evidence "
        "is used only inside substitute-function matching; demand arrival times "
        "and prices are deterministic simulation values; seller data is not "
        "included."
    )
    output["simulationPolicy"].update({
        "catalogProfileOrigin": PROFILE_ORIGIN,
        "profileRule": (
            "MFDS-grounded product facts; exact taxonomy facet mapping only"
        ),
        "catalogEligibilityPolicy": (
            "all input catalog IDs are assumed upstream-authorized; clustering "
            "does not infer eligibility from names, export markers, or record types"
        ),
        "functionEvidencePolicy": (
            "MFDS evidence readiness controls substitute proposals only and never "
            "blocks original-catalog board formation"
        ),
        "productRetrievalPolicy": (
            "fixed CPU E5 function-only Top-10; Top-20 only with no identity "
            "survivor in Top-10"
        ),
        "functionCoveragePolicy": (
            "IDENTITY_ONLY; all unapproved directional relations disabled"
        ),
        "textScorerVersion": (
            TEXT_SCORER_VERSION if text_similarity_scorer is not None else None
        ),
    })
    output["summary"].update({
        "groundedProductProfiles": profile_summary,
        "productRetrievalGate": retrieval_summary,
    })
    output["substituteAdmissionPlan"]["ruleVersion"] = RULE_VERSION
    output["invariantChecks"] = validate_grounded_hourly_simulation(
        output,
        allowed,
    )
    return output


def build_part_c_grounded_hourly_snapshot(
    simulation: Mapping[str, Any],
) -> dict[str, Any]:
    snapshot = build_part_c_hourly_board_snapshot(simulation)
    snapshot["schemaVersion"] = SNAPSHOT_SCHEMA
    snapshot["invariantChecks"] = simulation["invariantChecks"]
    board_fields = (
        "demandBoardId",
        "catalogId",
        "categoryId",
        "taxonomyVersion",
        "priceMin",
        "priceMax",
        "participantCount",
        "pendingSubstituteOfferCount",
        "status",
        "createdAt",
        "saleEndAt",
        "directDemandIds",
        "pendingSubstituteDemandIds",
    )
    snapshot["demandBoards"] = [
        {field: board[field] for field in board_fields}
        for board in simulation["demandBoards"]
    ]
    if "source" in simulation:
        source = simulation["source"]
        snapshot["sourceArtifacts"] = {
            "demandInputSha256": source["demandInputSha256"],
            "taxonomySha256": source["taxonomySha256"],
            "groundedProfilesSha256": source["groundedProfilesSha256"],
            "topCandidatesSha256": source["topCandidatesSha256"],
            "retrievalManifestSha256": source["retrievalManifestSha256"],
            "modelId": source["modelId"],
            "modelRevision": source["modelRevision"],
            "modelDevice": source["modelDevice"],
        }
    return snapshot


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create the grounded identity-only hourly Part C snapshot"
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--taxonomy", type=Path, required=True)
    parser.add_argument(
        "--profiles",
        type=Path,
        default=Path(
            "data/reports/grounded_catalog_substitution_evidence_v2/"
            "catalog_profile_candidates.csv"
        ),
    )
    parser.add_argument(
        "--top-candidates",
        type=Path,
        default=Path(
            "data/reports/product_retrieval_e5_small_function_only_v2/"
            "top_candidates.csv"
        ),
    )
    parser.add_argument(
        "--retrieval-manifest",
        type=Path,
        default=Path(
            "data/reports/product_retrieval_e5_small_function_only_v2/manifest.json"
        ),
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
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--board-output", type=Path, required=True)
    parser.add_argument("--model-path", type=Path)
    parser.add_argument("--model-batch-size", type=int, default=32)
    parser.add_argument("--start-at", default="2026-09-05T00:00:00+09:00")
    parser.add_argument("--arrival-hours", type=int, default=DEFAULT_ARRIVAL_HOURS)
    parser.add_argument(
        "--batch-interval-minutes",
        type=int,
        default=DEFAULT_BATCH_INTERVAL_MINUTES,
    )
    parser.add_argument("--min-participants", type=int, default=5)
    parser.add_argument(
        "--allow-synthetic-registration-times",
        action="store_true",
    )
    parser.add_argument("--allow-synthetic-prices", action="store_true")
    parser.add_argument(
        "--acknowledge-input-catalogs-are-upstream-authorized",
        action="store_true",
    )
    args = parser.parse_args()
    if not args.allow_synthetic_registration_times:
        parser.error("--allow-synthetic-registration-times is required")
    if not args.allow_synthetic_prices:
        parser.error("--allow-synthetic-prices is required")
    if not args.acknowledge_input_catalogs_are_upstream_authorized:
        parser.error(
            "--acknowledge-input-catalogs-are-upstream-authorized is required"
        )
    if args.arrival_hours < 1 or args.batch_interval_minutes < 1:
        parser.error("arrival and batch intervals must be positive")
    if args.model_batch_size < 1:
        parser.error("model-batch-size must be positive")
    for target in (args.output, args.board_output):
        if target.exists():
            raise RuntimeError(f"refusing to overwrite output: {target}")

    taxonomy = json.loads(args.taxonomy.read_text(encoding="utf-8"))
    parser_v046 = DemandConstraintParser.from_taxonomy(
        taxonomy,
        rules_path=args.rules,
        aliases_path=args.aliases,
    )
    with args.input.open(encoding="utf-8-sig", newline="") as source:
        rows = tuple(csv.DictReader(source))
    profiles = pd.read_csv(args.profiles, dtype=str, keep_default_na=False)
    top_candidates = pd.read_csv(
        args.top_candidates,
        dtype=str,
        keep_default_na=False,
    )
    retrieval_manifest = json.loads(
        args.retrieval_manifest.read_text(encoding="utf-8")
    )
    model_path = args.model_path or Path(
        retrieval_manifest["sourcePaths"]["modelPath"]
    )
    if not model_path.exists():
        raise FileNotFoundError(f"E5 model path does not exist: {model_path}")

    catalog_profiles, _ = build_grounded_catalog_board_profiles(
        rows,
        taxonomy,
        profiles,
    )
    semantic_queries = [
        text
        for row in rows
        for text in requirement_from_v046_row(row).semantic_preferences
    ]
    text_scorer = build_e5_preference_scorer(
        model_path,
        semantic_queries,
        (profile["semanticText"] for profile in catalog_profiles.values()),
        batch_size=args.model_batch_size,
    )
    output = simulate_grounded_hourly_demand_board_handoff(
        rows,
        taxonomy,
        profiles,
        top_candidates,
        start_at=datetime.fromisoformat(args.start_at.replace("Z", "+00:00")),
        arrival_window=timedelta(hours=args.arrival_hours),
        batch_interval=timedelta(minutes=args.batch_interval_minutes),
        min_participants=args.min_participants,
        canonicalize_value_code=parser_v046.canonicalize_value_code,
        text_similarity_scorer=text_scorer,
    )
    output["source"] = {
        "demandInput": str(args.input.resolve()),
        "demandInputSha256": _sha256(args.input),
        "taxonomy": str(args.taxonomy.resolve()),
        "taxonomySha256": _sha256(args.taxonomy),
        "groundedProfiles": str(args.profiles.resolve()),
        "groundedProfilesSha256": _sha256(args.profiles),
        "topCandidates": str(args.top_candidates.resolve()),
        "topCandidatesSha256": _sha256(args.top_candidates),
        "retrievalManifest": str(args.retrieval_manifest.resolve()),
        "retrievalManifestSha256": _sha256(args.retrieval_manifest),
        "modelId": retrieval_manifest["modelId"],
        "modelRevision": retrieval_manifest["modelRevision"],
        "modelDevice": "cpu",
    }
    snapshot = build_part_c_grounded_hourly_snapshot(output)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.board_output.parent.mkdir(parents=True, exist_ok=True)
    args.board_output.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "output": str(args.output),
        "boardOutput": str(args.board_output),
        **output["summary"],
        "invariantChecks": output["invariantChecks"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
