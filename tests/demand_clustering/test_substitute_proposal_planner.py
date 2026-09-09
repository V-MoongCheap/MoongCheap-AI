from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from moongcheap_ai.demand_clustering.backend_plan_client import (
    build_substitute_offer_plan_request,
)
from moongcheap_ai.demand_clustering.input_models import (
    DemandBoardInput,
    DemandInput,
)
from moongcheap_ai.demand_clustering.postgres_reader import ClusteringInputBatch
from moongcheap_ai.demand_clustering.substitute_proposal_planner import (
    ClaimIndexedSubstituteProposalPlanner,
)
from moongcheap_ai.demand_constraints import DemandConstraintParser


ROOT = Path(__file__).parents[2]
NOW = datetime.fromisoformat("2026-09-07T12:00:00+09:00")
CATEGORY = "health-functional-food:protein"


def profile(
    catalog_id: int,
    claims: list[str],
    *,
    name: str,
    form: str,
    status: str = "EVIDENCE_READY",
) -> dict[str, object]:
    return {
        "catalog_id": str(catalog_id),
        "product_name": name,
        "service_category_id": CATEGORY,
        "taxonomy_version": "v2.1",
        "product_form": form,
        "functional_ingredients_json": json.dumps(["단백질"]),
        "main_functionality_claim_ids_json": json.dumps(claims),
        "main_functionality_claim_texts_json": json.dumps(
            [f"기능 {claim}" for claim in claims]
        ),
        "intake_method_text": "1일 1회 섭취",
        "profile_status": status,
    }


def demand(
    demand_id: int,
    catalog_id: int,
    extra_requirement: str,
) -> DemandInput:
    return DemandInput(
        id=demand_id,
        catalog_id=catalog_id,
        created_at=NOW - timedelta(hours=1),
        updated_at=NOW - timedelta(hours=1),
        desired_price_min=10_001,
        desired_price_max=30_000,
        quantity=2,
        extra_requirement=extra_requirement,
        is_substitutable=True,
        status="UNASSIGNED",
        desire_end_at=NOW + timedelta(days=1),
    )


def board(
    board_id: int,
    catalog_id: int,
    *,
    price_max: int = 20_000,
    participant_count: int = 5,
) -> DemandBoardInput:
    return DemandBoardInput(
        id=board_id,
        catalog_id=catalog_id,
        participant_count=participant_count,
        created_at=NOW - timedelta(hours=1),
        sale_end_at=NOW + timedelta(days=2),
        price_min=10_001,
        price_max=price_max,
        status="GB_GATHERING",
    )


def planner(
    profiles: pd.DataFrame,
    *,
    text_similarity_scorer=None,
) -> ClaimIndexedSubstituteProposalPlanner:
    taxonomy = json.loads(
        (
            ROOT / "tests/demand_constraints/fixtures/v042_taxonomy.json"
        ).read_text(encoding="utf-8")
    )
    parser = DemandConstraintParser.from_taxonomy(
        taxonomy,
        rules_path=ROOT / "config/demand_constraint_rules.json",
        aliases_path=ROOT / "config/demand_constraint_aliases.json",
    )

    def text_score(query: str, candidate: str) -> float:
        return 0.9 if "딸기맛" in candidate else 0.1

    return ClaimIndexedSubstituteProposalPlanner(
        profiles,
        taxonomy,
        parser,
        text_similarity_scorer=text_similarity_scorer or text_score,
    )


def test_claim_gate_runs_before_structured_preference_ranking() -> None:
    profiles = pd.DataFrame([
        profile(101, ["protein"], name="원상품", form="정"),
        profile(201, ["protein", "immune"], name="분말 후보", form="분말"),
        profile(202, ["immune"], name="claim 미충족", form="분말"),
        profile(203, ["protein"], name="가격 초과", form="분말"),
    ])
    result = planner(profiles).plan(
        ClusteringInputBatch(
            demands=(demand(1, 101, "가능하면 분말인 제품으로 부탁해요."),),
            boards=(
                board(31, 201),
                board(32, 202, participant_count=100),
                board(33, 203, price_max=40_000),
            ),
        ),
        as_of=NOW,
    )

    assert len(result.proposals) == 1
    assert result.proposals[0]["demandBoardId"] == 31
    assert result.proposals[0]["substituteCatalogId"] == 201
    assert result.proposals[0]["effectiveRequirementMode"] == "STRUCTURED"
    assert result.decisions[0].selected_board is not None
    assert result.decisions[0].selected_board.structured_preference_score == 1.0
    assert {item.demand_board_id for item in result.decisions[0].rejected_boards} == {
        33
    }


def test_passthrough_uses_injected_semantic_scorer_after_claim_gate() -> None:
    profiles = pd.DataFrame([
        profile(101, ["protein"], name="원상품", form="정"),
        profile(201, ["protein"], name="일반 단백질", form="정"),
        profile(202, ["protein"], name="딸기맛 단백질", form="정"),
    ])
    result = planner(profiles).plan(
        ClusteringInputBatch(
            demands=(demand(1, 101, "딸기맛 제품이면 좋겠어요."),),
            boards=(board(31, 201), board(32, 202)),
        ),
        as_of=NOW,
    )

    assert result.proposals[0]["demandBoardId"] == 32
    assert result.proposals[0]["effectiveRequirementMode"] == "SEMANTIC_TEXT"
    assert result.decisions[0].selected_board is not None
    assert result.decisions[0].selected_board.text_similarity_score == 0.9


def test_passthrough_prepares_only_semantic_batch_inputs() -> None:
    class BatchScorer:
        def __init__(self) -> None:
            self.prepared: tuple[tuple[str, ...], tuple[str, ...]] | None = None

        def prepare(
            self,
            queries: tuple[str, ...],
            passages: tuple[str, ...],
        ) -> None:
            self.prepared = (queries, passages)

        def __call__(self, query: str, passage: str) -> float:
            return 0.9 if "딸기맛" in passage else 0.1

    scorer = BatchScorer()
    profiles = pd.DataFrame([
        profile(101, ["protein"], name="원상품", form="정"),
        profile(201, ["protein"], name="일반 단백질", form="정"),
        profile(202, ["protein"], name="딸기맛 단백질", form="정"),
    ])
    planner(profiles, text_similarity_scorer=scorer).plan(
        ClusteringInputBatch(
            demands=(
                demand(1, 101, "딸기맛 제품이면 좋겠어요."),
                demand(2, 101, "가능하면 정인 제품으로 부탁해요."),
            ),
            boards=(board(31, 201), board(32, 202)),
        ),
        as_of=NOW,
    )

    assert scorer.prepared is not None
    queries, passages = scorer.prepared
    assert queries == ("딸기맛 제품이면 좋겠어요.",)
    assert len(passages) == 2
    assert all("상품명:" in passage for passage in passages)


def test_missing_function_evidence_is_skipped_without_runtime_review() -> None:
    profiles = pd.DataFrame([
        profile(
            101,
            [],
            name="근거 부족 원상품",
            form="정",
            status="INSUFFICIENT_EVIDENCE",
        ),
        profile(201, ["protein"], name="후보", form="정"),
    ])
    result = planner(profiles).plan(
        ClusteringInputBatch(
            demands=(demand(1, 101, ""),),
            boards=(board(31, 201),),
        ),
        as_of=NOW,
    )

    assert result.proposals == ()
    assert result.decisions == ()
    assert result.skipped_demands[0].reason_code == (
        "SOURCE_FUNCTION_EVIDENCE_NOT_READY"
    )


def test_rejects_backend_catalog_without_runtime_profile() -> None:
    profiles = pd.DataFrame([
        profile(101, ["protein"], name="원상품", form="정"),
    ])

    with pytest.raises(ValueError, match="202"):
        planner(profiles).validate_input_profile_coverage(
            ClusteringInputBatch(
                demands=(demand(1, 101, ""),),
                boards=(board(31, 202),),
            )
        )


def test_callable_output_projects_to_backend_offer_contract() -> None:
    profiles = pd.DataFrame([
        profile(101, ["protein"], name="원상품", form="정"),
        profile(201, ["protein"], name="후보", form="정"),
    ])
    proposals = planner(profiles)(
        ClusteringInputBatch(
            demands=(demand(1, 101, ""),),
            boards=(board(31, 201),),
        ),
        as_of=NOW,
    )

    request = build_substitute_offer_plan_request(
        proposals,
        planned_at=NOW,
        rule_version="substitute-admission-v1",
    )

    assert request["proposals"] == [{
        "demandId": 1,
        "expectedOriginalCatalogId": 101,
        "substituteCatalogId": 201,
        "demandBoardId": 31,
    }]


def test_rejection_excludes_only_the_exact_demand_board_pair() -> None:
    profiles = pd.DataFrame([
        profile(101, ["protein"], name="원상품", form="정"),
        profile(201, ["protein"], name="후보 상품", form="정"),
    ])
    result = planner(profiles).plan(
        ClusteringInputBatch(
            demands=(demand(1, 101, ""), demand(2, 101, "")),
            boards=(
                board(31, 201, participant_count=20),
                board(32, 201, participant_count=5),
            ),
            rejected_demand_board_pairs=frozenset({(1, 31)}),
        ),
        as_of=NOW,
    )

    # A different board with the same catalog remains eligible for demand 1;
    # demand 2 may still receive the board that demand 1 rejected.
    assert [(row["demandId"], row["demandBoardId"]) for row in result.proposals] == [
        (1, 32), (2, 31),
    ]


def test_no_offer_when_all_candidate_boards_were_rejected() -> None:
    profiles = pd.DataFrame([
        profile(101, ["protein"], name="원상품", form="정"),
        profile(201, ["protein"], name="후보 상품", form="정"),
    ])
    result = planner(profiles).plan(
        ClusteringInputBatch(
            demands=(demand(1, 101, ""),),
            boards=(board(31, 201), board(32, 201)),
            rejected_demand_board_pairs=frozenset({(1, 31), (1, 32)}),
        ),
        as_of=NOW,
    )

    assert result.proposals == ()
    assert result.decisions[0].selected_board is None


def test_rejected_board_is_excluded_before_semantic_preparation() -> None:
    class Scorer:
        def prepare(self, queries, passages):
            assert queries == ("딸기맛 제품이면 좋겠어요.",)
            assert len(passages) == 1
            assert "허용 후보" in passages[0]
            assert "거절 후보" not in passages[0]

        def __call__(self, query, passage):
            assert "거절 후보" not in passage
            return 0.9

    profiles = pd.DataFrame([
        profile(101, ["protein"], name="원상품", form="정"),
        profile(201, ["protein"], name="딸기맛 거절 후보", form="정"),
        profile(202, ["protein"], name="허용 후보", form="정"),
    ])
    result = planner(profiles, text_similarity_scorer=Scorer()).plan(
        ClusteringInputBatch(
            demands=(demand(1, 101, "딸기맛 제품이면 좋겠어요."),),
            boards=(board(31, 201, participant_count=100), board(32, 202)),
            rejected_demand_board_pairs=frozenset({(1, 31)}),
        ),
        as_of=NOW,
    )

    assert result.proposals[0]["demandBoardId"] == 32
