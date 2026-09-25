from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from moongcheap_ai.demand_clustering.catalog_seed_planner import (
    CatalogSeedSubstituteProposalPlanner,
    build_runtime_seed_catalog,
)
from moongcheap_ai.demand_clustering.input_models import (
    DemandBoardInput,
    DemandInput,
)
from moongcheap_ai.demand_clustering.postgres_reader import ClusteringInputBatch
from moongcheap_ai.demand_constraints import DemandConstraintParser

ROOT = Path(__file__).parents[2]
NOW = datetime.fromisoformat("2026-09-25T12:00:00+09:00")
CATEGORY = "health-functional-food:protein"


def seed_row(
    source_id: int,
    name: str,
    *,
    leaf: str = "cat-v5-protein",
    category: str = CATEGORY,
) -> dict[str, str]:
    return {
        "catalog_seed_id": f"catalog-seed-domeggook-{source_id}",
        "source_product_id": str(source_id),
        "name": name,
        "category_seed_id": leaf,
        "source_category_path": "식품 > 건강식품 > 단백질",
        "source_category_id": category,
        "status": "ACTIVE",
    }


def demand(catalog_id: int, name: str, requirement: str) -> DemandInput:
    return DemandInput(
        id=1,
        catalog_id=catalog_id,
        catalog_name=name,
        created_at=NOW - timedelta(hours=1),
        updated_at=NOW - timedelta(hours=1),
        desired_price_min=10_001,
        desired_price_max=30_000,
        quantity=2,
        extra_requirement=requirement,
        is_substitutable=True,
        status="UNASSIGNED",
        desire_end_at=NOW + timedelta(days=1),
    )


def board(board_id: int, catalog_id: int, name: str) -> DemandBoardInput:
    return DemandBoardInput(
        id=board_id,
        catalog_id=catalog_id,
        catalog_name=name,
        participant_count=5,
        created_at=NOW - timedelta(hours=1),
        sale_end_at=NOW + timedelta(days=1),
        price_min=10_001,
        price_max=20_000,
    )


def planner(seed: pd.DataFrame) -> CatalogSeedSubstituteProposalPlanner:
    taxonomy = json.loads(
        (ROOT / "tests/demand_constraints/fixtures/v042_taxonomy.json").read_text(
            encoding="utf-8"
        )
    )
    parser = DemandConstraintParser.from_taxonomy(
        taxonomy,
        rules_path=ROOT / "config/demand_constraint_rules.json",
        aliases_path=ROOT / "config/demand_constraint_aliases.json",
    )
    return CatalogSeedSubstituteProposalPlanner(
        seed,
        taxonomy,
        parser,
        text_similarity_scorer=lambda _query, _candidate: 0.5,
    )


def test_v5_seed_needs_no_claim_columns_and_keeps_sentence_structure() -> None:
    seed = pd.DataFrame([
        seed_row(101, "단백질 정제 원상품"),
        seed_row(201, "단백질 분말 대체상품"),
        seed_row(202, "단백질 분말 다른세부카테고리", leaf="cat-v5-other"),
    ])

    result = planner(seed).plan(
        ClusteringInputBatch(
            demands=(demand(101, "단백질 정제 원상품", "가능하면 분말이면 좋겠어요."),),
            boards=(
                board(31, 201, "단백질 분말 대체상품"),
                board(32, 202, "단백질 분말 다른세부카테고리"),
            ),
        ),
        as_of=NOW,
    )

    assert result.proposals[0]["demandBoardId"] == 31
    assert result.proposals[0]["effectiveRequirementMode"] == "STRUCTURED"
    assert result.decisions[0].selected_board is not None
    assert result.decisions[0].selected_board.structured_preference_score == 1.0


def test_v5_seed_keeps_must_and_exclude_as_hard_gates() -> None:
    seed = pd.DataFrame([
        seed_row(101, "원상품 정제"),
        seed_row(201, "판토텐산 분말"),
        seed_row(202, "비오틴 분말"),
    ])

    result = planner(seed).plan(
        ClusteringInputBatch(
            demands=(demand(
                101,
                "원상품 정제",
                "비오틴은 절대 포함 금지이고, 분말은 꼭 포함해 주세요.",
            ),),
            boards=(
                board(31, 201, "판토텐산 분말"),
                board(32, 202, "비오틴 분말"),
            ),
        ),
        as_of=NOW,
    )

    assert result.proposals[0]["demandBoardId"] == 31
    assert result.proposals[0]["effectiveRequirementMode"] == "STRUCTURED"
    rejected = result.decisions[0].rejected_boards
    assert rejected[0].demand_board_id == 32
    assert "EXCLUDED_VALUE:functional_ingredients" in rejected[0].reason_codes


def test_missing_or_unmapped_seed_product_skips_only_substitution() -> None:
    seed = pd.DataFrame([
        seed_row(101, "매핑 상품"),
        seed_row(201, "카테고리 미매핑 상품", category=""),
    ])
    runtime = build_runtime_seed_catalog(
        seed,
        json.loads(
            (ROOT / "tests/demand_constraints/fixtures/v042_taxonomy.json").read_text(
                encoding="utf-8"
            )
        ),
    )
    assert set(runtime) == {"매핑 상품", "카테고리 미매핑 상품"}

    missing = planner(seed).plan(
        ClusteringInputBatch(
            demands=(demand(999, "사용자 신규 상품", ""),),
            boards=(board(31, 101, "매핑 상품"),),
        ),
        as_of=NOW,
    )
    unmapped = planner(seed).plan(
        ClusteringInputBatch(
            demands=(demand(201, "카테고리 미매핑 상품", ""),),
            boards=(board(31, 101, "매핑 상품"),),
        ),
        as_of=NOW,
    )

    assert missing.proposals == ()
    assert missing.skipped_demands[0].reason_code == "SOURCE_CATALOG_SEED_NOT_FOUND"
    assert unmapped.proposals == ()
    assert unmapped.skipped_demands[0].reason_code == "SOURCE_CATEGORY_NOT_MAPPED"
