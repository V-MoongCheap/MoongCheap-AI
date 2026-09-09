from __future__ import annotations

import pytest

from moongcheap_ai.demand_clustering.evaluation.substitute_review_set import (
    SAMPLING_STRATA,
    build_substitute_product_pair_review_set,
)


def product(
    product_id: str,
    *,
    name: str,
    product_type: str,
    ingredients: str,
    functionality: str,
    intake: str = "1일 1회 섭취",
    form: str = "정제",
) -> dict[str, str]:
    return {
        "source_product_id": product_id,
        "name": name,
        "product_type": product_type,
        "product_form": form,
        "functional_ingredients": ingredients,
        "main_functionality": functionality,
        "intake_method": intake,
    }


def fixture_products() -> list[dict[str, str]]:
    return [
        product(
            "eye-1",
            name="루테인 A",
            product_type="루테인",
            ingredients="루테인",
            functionality="눈 건강에 도움을 줄 수 있음",
        ),
        product(
            "eye-2",
            name="루테인 B",
            product_type="루테인",
            ingredients="루테인, 지아잔틴",
            functionality="눈 건강에 도움을 줄 수 있음",
        ),
        product(
            "eye-3",
            name="눈 건강 C",
            product_type="루테인",
            ingredients="지아잔틴",
            functionality="눈 건강에 도움을 줄 수 있음",
        ),
        product(
            "eye-4",
            name="눈 건강 D",
            product_type="루테인",
            ingredients="베타카로틴",
            functionality="어두운 곳에서 시각 적응에 필요",
        ),
        product(
            "cross-eye",
            name="눈 공통원료",
            product_type="루테인",
            ingredients="공통원료",
            functionality="눈 건강 유지",
        ),
        product(
            "cross-liver",
            name="간 공통원료",
            product_type="밀크씨슬",
            ingredients="공통원료",
            functionality="간 건강 유지",
        ),
        product(
            "liver-2",
            name="간 건강",
            product_type="밀크씨슬",
            ingredients="실리마린",
            functionality="간 건강에 도움을 줄 수 있음",
        ),
        product(
            "material",
            name="루테인 원료",
            product_type="루테인",
            ingredients="루테인",
            functionality="눈 건강",
            intake="건강기능식품 제조 시 원료로 사용",
        ),
        product(
            "missing",
            name="근거 부족",
            product_type="루테인",
            ingredients="미상원료",
            functionality="",
            intake="",
        ),
    ]


def test_builds_reciprocal_unlabeled_pairs_across_review_strata() -> None:
    rows, summary = build_substitute_product_pair_review_set(
        fixture_products(),
        directional_pairs_per_stratum=2,
        seed=7,
    )

    observed = {row["sampling_stratum"] for row in rows}
    assert {
        "SAME_CATEGORY_SHARED_INGREDIENT",
        "SAME_CATEGORY_HIGH_FUNCTION_TEXT",
        "SAME_CATEGORY_NO_SHARED_INGREDIENT",
        "CROSS_CATEGORY_SHARED_INGREDIENT",
        "NON_FINISHED_PRODUCT_PAIR",
        "MISSING_REQUIRED_EVIDENCE",
    }.issubset(observed)
    assert observed.issubset(SAMPLING_STRATA)
    assert all(row["gold_label"] == "" for row in rows)
    assert all(row["critical_negative"] == "" for row in rows)
    assert summary["goldLabelsPrepopulated"] is False
    assert summary["runtimeReviewStateCreated"] is False

    reciprocal_groups: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        reciprocal_groups.setdefault(row["reciprocal_group_id"], []).append(row)
    assert all(len(group) == 2 for group in reciprocal_groups.values())
    for group in reciprocal_groups.values():
        left, right = group
        assert left["source_product_id"] == right["candidate_product_id"]
        assert left["candidate_product_id"] == right["source_product_id"]


def test_output_and_source_split_are_input_order_independent() -> None:
    products = fixture_products()
    forward, _summary = build_substitute_product_pair_review_set(
        products,
        directional_pairs_per_stratum=2,
        seed=11,
    )
    reverse, _summary = build_substitute_product_pair_review_set(
        reversed(products),
        directional_pairs_per_stratum=2,
        seed=11,
    )

    assert forward == reverse
    splits_by_source: dict[str, set[str]] = {}
    for row in forward:
        splits_by_source.setdefault(row["source_product_id"], set()).add(
            row["split"]
        )
    assert all(len(splits) == 1 for splits in splits_by_source.values())


def test_reports_stratum_shortfall_instead_of_inventing_pairs() -> None:
    rows, summary = build_substitute_product_pair_review_set(
        fixture_products()[:2],
        directional_pairs_per_stratum=4,
    )

    assert len(rows) == 2
    assert summary["samplingStratumCounts"][
        "SAME_CATEGORY_SHARED_INGREDIENT"
    ] == 2
    assert summary["samplingStratumShortfalls"][
        "SAME_CATEGORY_SHARED_INGREDIENT"
    ] == 2


def test_rejects_odd_quota_and_duplicate_product_ids() -> None:
    with pytest.raises(ValueError, match="positive even number"):
        build_substitute_product_pair_review_set(
            fixture_products(),
            directional_pairs_per_stratum=3,
        )

    duplicate = fixture_products()[0]
    with pytest.raises(ValueError, match="duplicate source_product_id"):
        build_substitute_product_pair_review_set((duplicate, duplicate))
