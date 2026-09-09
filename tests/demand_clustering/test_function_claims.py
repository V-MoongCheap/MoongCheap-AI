from __future__ import annotations

import pandas as pd

from moongcheap_ai.demand_clustering.evaluation.function_claims import (
    build_function_claim_candidates,
    extract_atomic_function_claims,
)


def test_extracts_numbered_and_shared_suffix_claims() -> None:
    numbered = extract_atomic_function_claims(
        "(1) 결합조직 형성과 기능유지에 필요\n"
        "(2) 철의 흡수에 필요\n"
        "(3) 항산화 작용을 하여 세포를 보호하는데 필요"
    )
    shared = extract_atomic_function_claims(
        "(1) 기억력 개선･혈행 개선에 도움을 줄 수 있음"
    )

    assert numbered.parse_status == "PARSED_MULTI"
    assert numbered.claims == (
        "결합조직 형성과 기능유지에 필요",
        "철의 흡수에 필요",
        "항산화 작용을 하여 세포를 보호하는데 필요",
    )
    assert shared.parse_status == "PARSED_MULTI"
    assert shared.claims == (
        "기억력 개선에 도움을 줄 수 있음",
        "혈행 개선에 도움을 줄 수 있음",
    )


def test_preserves_middots_inside_anatomy_and_parentheses() -> None:
    result = extract_atomic_function_claims(
        "(국문) 기관·기관지 상태(기침·가래 등) 개선에 도움을 줄 수 있음 "
        "(영문) May help respiratory health"
    )

    assert result.parse_status == "PARSED_SINGLE"
    assert result.claims == (
        "기관·기관지 상태(기침·가래 등) 개선에 도움을 줄 수 있음",
    )


def test_splits_comma_goal_list_but_preserves_metabolic_list() -> None:
    gut = extract_atomic_function_claims(
        "장내 유익균 증식, 유해균 억제, 배변활동에 도움을 줄 수 있음"
    )
    metabolism = extract_atomic_function_claims(
        "(1) 지방, 탄수화물, 단백질 대사와 에너지 생성에 필요"
    )

    assert gut.claims == (
        "장내 유익균 증식에 도움을 줄 수 있음",
        "유해균 억제에 도움을 줄 수 있음",
        "배변활동에 도움을 줄 수 있음",
    )
    assert metabolism.parse_status == "PARSED_SINGLE"
    assert metabolism.claims == (
        "지방, 탄수화물, 단백질 대사와 에너지 생성에 필요",
    )


def test_does_not_treat_interleukin_number_as_enumerator() -> None:
    result = extract_atomic_function_claims(
        "인터루킨 4 감소를 통한 면역조절에 도움을 줄 수 있음"
    )

    assert result.parse_status == "PARSED_SINGLE"
    assert result.claims == (
        "인터루킨 4 감소를 통한 면역조절에 도움을 줄 수 있음",
    )


def test_treats_antioxidant_as_valid_short_claim() -> None:
    result = extract_atomic_function_claims(
        "(1) 기능성 내용 : 항산화 . 구강에서의 항균작용에 도움을 줄 수 있음"
    )

    assert result.parse_status == "PARSED_MULTI"
    assert result.claims == (
        "항산화",
        "구강에서의 항균작용에 도움을 줄 수 있음",
    )


def test_builds_candidates_and_dereferences_reference_function() -> None:
    references = pd.DataFrame([
        {
            "category_reference_name": "마리골드꽃추출물",
            "main_functionality": "눈 건강에 도움을 줄 수 있음",
        },
        {
            "category_reference_name": "마리골드꽃추출물(제2025-7호)",
            "main_functionality": "기준 및 규격 마리골드꽃추출물에 따름",
        },
        {
            "category_reference_name": "누락 원료",
            "main_functionality": "",
        },
        {
            "category_reference_name": "복합 원료",
            "main_functionality": (
                "(국문) ① 눈 건강에 도움을 줄 수 있음 "
                "② 피부 보습에 도움을 줄 수 있음"
            ),
        },
    ])

    signatures, claims, summary = build_function_claim_candidates(references)

    assert len(signatures) == 2
    assert sorted(signatures["reference_count"].tolist()) == [1, 2]
    assert signatures["uses_dereferenced_function"].map(bool).sum() == 1
    compound_claims = claims.loc[
        claims["source_reference_names"].eq("복합 원료"),
        "claim_text_candidate",
    ].tolist()
    assert compound_claims == [
        "눈 건강에 도움을 줄 수 있음",
        "피부 보습에 도움을 줄 수 있음",
    ]
    assert summary["referenceRows"] == 4
    assert summary["emptyFunctionRows"] == 1
    assert summary["indirectReferenceRows"] == 1
    assert summary["dereferencedRows"] == 1
