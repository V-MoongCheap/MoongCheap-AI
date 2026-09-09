from __future__ import annotations

import pandas as pd

from moongcheap_ai.demand_clustering.evaluation.evidence_analysis import (
    analyze_substitute_evidence,
)


def test_profiles_evidence_and_conservative_reference_linkage() -> None:
    products = pd.DataFrame([
        {
            "source_product_id": "1",
            "name": "홍삼 완제품",
            "product_type": "홍삼제품",
            "main_functionality": "면역력 증진에 도움을 줄 수 있음",
            "functional_ingredients": "홍삼제품",
            "product_form": "액상",
            "intake_method": "1일 1회 섭취",
        },
        {
            "source_product_id": "2",
            "name": "프로바이오틱스 원료",
            "product_type": "프로바이오틱스",
            "main_functionality": "배변활동 원활에 도움을 줄 수 있음",
            "functional_ingredients": "프로바이오틱스",
            "product_form": "분말",
            "intake_method": "건강기능식품 원료로 사용",
        },
        {
            "source_product_id": "3",
            "name": "근거 일부 누락",
            "product_type": "홍삼",
            "main_functionality": "면역력 증진에 도움을 줄 수 있음",
            "functional_ingredients": "홍삼",
            "product_form": "",
            "intake_method": "",
        },
        {
            "source_product_id": "4",
            "name": "미지 상품",
            "product_type": "미지 유형",
            "main_functionality": "알 수 없는 기능에 도움",
            "functional_ingredients": "미지 원료",
            "product_form": "정",
            "intake_method": "1일 1회 섭취",
        },
    ])
    references = pd.DataFrame([
        {
            "category_reference_name": "홍삼",
            "main_functionality": "면역력 증진에 도움을 줄 수 있음",
            "ingredient_name": "진세노사이드",
        },
        {
            "category_reference_name": "프로바이오틱스",
            "main_functionality": "배변활동 원활에 도움을 줄 수 있음",
            "ingredient_name": "프로바이오틱스",
        },
    ])

    summary, unmatched_types, ingredient_issues, divergence = analyze_substitute_evidence(
        products, references
    )

    assert summary["i0030"]["coreEvidenceCompleteRows"] == 4
    assert summary["i0030"]["strictEvidenceCompleteRows"] == 3
    assert summary["i0030"]["finishedCoreReadyRows"] == 2
    linkage = summary["deterministicReferenceLinkage"]
    assert linkage["productTypeExactMatchRows"] == 2
    assert linkage["productTypeSafeMatchRows"] == 3
    assert linkage["structuredReferenceMatchRows"] == 3
    assert unmatched_types.to_dict("records") == [
        {"product_type": "미지 유형", "product_count": 1}
    ]
    assert len(divergence) == 1
    assert ingredient_issues.to_dict("records") == [{
        "resolution_status": "UNMATCHED",
        "ingredient_token": "미지 원료",
        "occurrence_count": 1,
        "candidate_reference_names": "",
        "example_product_ids": "4",
    }]
    assert summary["declaredVsReconstructedFunctionText"][
        "exactNormalizedMatchRows"
    ] == 1


def test_does_not_collapse_ambiguous_recognized_ingredients() -> None:
    products = pd.DataFrame([
        {
            "source_product_id": "1",
            "name": "강황 완제품",
            "product_type": "강황 추출물",
            "main_functionality": "인지기능 개선에 도움을 줄 수 있음",
            "functional_ingredients": "강황 추출물",
            "product_form": "정",
            "intake_method": "1일 1회 섭취",
        },
        {
            "source_product_id": "2",
            "name": "인정번호 제품",
            "product_type": "강황추출물(기능성원료인정제2025-51호)",
            "main_functionality": "인지기능 개선에 도움을 줄 수 있음",
            "functional_ingredients": "강황추출물(기능성원료인정제2025-51호)",
            "product_form": "정",
            "intake_method": "1일 1회 섭취",
        },
    ])
    references = pd.DataFrame([
        {
            "category_reference_name": "강황추출물(제2025-51호)",
            "main_functionality": "인지기능 개선에 도움을 줄 수 있음",
            "ingredient_name": "강황",
        },
        {
            "category_reference_name": "강황추출물(제2023-5호)",
            "main_functionality": "근력 개선에 도움을 줄 수 있음",
            "ingredient_name": "강황",
        },
    ])

    summary, _, issues, _ = analyze_substitute_evidence(products, references)

    statuses = summary["deterministicReferenceLinkage"][
        "ingredientResolutionStatusCounts"
    ]
    assert statuses == {"AMBIGUOUS_REFERENCE": 1, "RECOGNITION_ID": 1}
    assert issues.iloc[0]["ingredient_token"] == "강황 추출물"
    assert summary["structuredFunctionReconstruction"][
        "eligibleProductStatusCounts"
    ] == {
        "REFERENCE_AMBIGUOUS": 1,
        "STRUCTURED_RECONSTRUCTION_READY": 1,
    }


def test_dereferences_i2710_function_pointer() -> None:
    products = pd.DataFrame([{
        "source_product_id": "1",
        "name": "눈 건강 제품",
        "product_type": "마리골드꽃추출물(제2025-7호)",
        "main_functionality": "황반색소밀도를 유지하여 눈 건강에 도움",
        "functional_ingredients": "마리골드꽃추출물(제2025-7호)",
        "product_form": "정",
        "intake_method": "1일 1회 섭취",
    }])
    references = pd.DataFrame([
        {
            "category_reference_name": "마리골드꽃추출물",
            "main_functionality": "황반색소밀도를 유지하여 눈 건강에 도움",
            "ingredient_name": "루테인",
        },
        {
            "category_reference_name": "마리골드꽃추출물(제2025-7호)",
            "main_functionality": "기준 및 규격 마리골드꽃추출물에 따름",
            "ingredient_name": "루테인",
        },
    ])

    summary, _, _, divergence = analyze_substitute_evidence(products, references)

    assert divergence.iloc[0]["reconstructed_i2710_functionality"] == (
        "황반색소밀도를 유지하여 눈 건강에 도움"
    )
    assert summary["i2710"]["indirectFunctionReferenceRows"] == 1
    assert summary["declaredVsReconstructedFunctionText"][
        "productsWithIndirectReferenceFunction"
    ] == 1
