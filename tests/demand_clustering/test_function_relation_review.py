from __future__ import annotations

import pandas as pd

from moongcheap_ai.demand_clustering.evaluation.function_relation_review import (
    build_function_relation_review_set,
)


def _claims() -> pd.DataFrame:
    values = [
        ("bone", "뼈 건강에 도움을 줄 수 있음", "칼슘"),
        ("liver", "간 건강에 도움을 줄 수 있음", "밀크씨슬"),
        ("fatigue", "피로 개선에 도움을 줄 수 있음", "홍삼"),
        ("eye-fatigue", "눈의 피로 개선에 도움을 줄 수 있음", "고시 원료"),
        ("cholesterol", "혈중 콜레스테롤 개선에 도움을 줄 수 있음", "대두단백"),
        ("cholesterol-level", "혈중 콜레스테롤 수치 개선에 도움을 줄 수 있음", "개별 원료"),
        ("body-fat", "체지방 감소에 도움을 줄 수 있음", "녹차"),
        ("exercise-body-fat", "근력운동과 병행 시 체지방 감소에 도움을 줄 수 있음", "개별 원료2"),
        ("blood-clot", "정상적인 혈액응고에 필요", "비타민 K"),
        ("bowel", "배변활동 원활에 도움을 줄 수 있음", "차전자피"),
    ]
    return pd.DataFrame([
        {
            "claim_key_candidate": key,
            "claim_text_candidate": text,
            "source_reference_names": reference,
        }
        for key, text, reference in values
    ])


def test_builds_blinded_bidirectional_review_rows_deterministically() -> None:
    claims = _claims()
    review, audit, manifest = build_function_relation_review_set(
        claims,
        pairs_per_stratum=1,
        seed="test-seed",
    )
    shuffled_review, shuffled_audit, shuffled_manifest = (
        build_function_relation_review_set(
            claims.sample(frac=1, random_state=7),
            pairs_per_stratum=1,
            seed="test-seed",
        )
    )

    pd.testing.assert_frame_equal(review, shuffled_review)
    pd.testing.assert_frame_equal(audit, shuffled_audit)
    assert manifest == shuffled_manifest
    assert len(review) == manifest["directedReviewRows"]
    assert len(review) == 2 * manifest["undirectedPairs"]
    assert set(review["coverage_label"]) == {""}
    assert "sampling_stratum" not in review.columns
    assert "character_bigram_similarity" not in review.columns
    assert set(audit["direction_id"]) == set(review["direction_id"])


def test_rejects_nonpositive_sample_size() -> None:
    try:
        build_function_relation_review_set(_claims(), pairs_per_stratum=0)
    except ValueError as error:
        assert str(error) == "pairs_per_stratum must be positive"
    else:
        raise AssertionError("expected ValueError")
