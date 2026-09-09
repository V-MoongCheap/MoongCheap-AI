from __future__ import annotations

import json

import pandas as pd
import pytest

from moongcheap_ai.demand_clustering.evaluation.llm_function_relation_review import (
    adjudications_to_status_frame,
    build_adjudication_prompt,
    build_review_prompt,
    decisions_to_review_frame,
)


def _review_frame() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "review_order": index + 1,
            "direction_id": f"direction-{index}",
            "source_claim_id": f"source-{index}",
            "source_claim_text": f"원기능 {index}",
            "candidate_claim_id": f"candidate-{index}",
            "candidate_claim_text": f"후보 기능 {index}",
            "coverage_label": "",
            "reason_code": "",
            "reviewer_id": "REVIEWER_A",
            "review_note": "",
        }
        for index in range(2)
    ])


def _response() -> str:
    return json.dumps({
        "decisions": [
            {
                "direction_id": "direction-1",
                "coverage_label": "DOES_NOT_COVER",
                "reason_code": "DIFFERENT_ENDPOINT",
                "note": "기능 종점이 다르다.",
            },
            {
                "direction_id": "direction-0",
                "coverage_label": "COVERS",
                "reason_code": "SAME_ENDPOINT_EQUIVALENT_WORDING",
                "note": "같은 기능을 다르게 표현했다.",
            },
        ]
    }, ensure_ascii=False)


def test_prompt_exposes_only_claim_questions() -> None:
    review = _review_frame()
    review["source_reference_names"] = "hidden ingredient"
    review["sampling_stratum"] = "hidden stratum"

    prompt = build_review_prompt(review)

    assert "direction-0" in prompt
    assert "원기능 0" in prompt
    assert "hidden ingredient" not in prompt
    assert "hidden stratum" not in prompt


def test_v2_prompt_separates_scope_and_endpoint_reasons() -> None:
    prompt = build_review_prompt(_review_frame(), rubric_version="v2")

    assert "SAME_ENDPOINT_BROADER_POPULATION_OR_CONTEXT" in prompt
    assert "SOURCE_ENDPOINT_NOT_FULLY_COVERED" in prompt
    assert "A의 제한을 B가 제거한 것은 누락이 아니라" in prompt


def test_v21_prompt_restricts_body_target_and_scope_reasons() -> None:
    prompt = build_review_prompt(_review_frame(), rubric_version="v2.1")

    assert "A와 B가 모두 구체적인 해부학적 부위" in prompt
    assert "CANDIDATE_SCOPE_NARROWER는 B가 A에 없던" in prompt


def test_v22_prompt_defines_mutually_exclusive_reason_precedence() -> None:
    prompt = build_review_prompt(_review_frame(), rubric_version="v2.2")

    assert "reason_code 차이로 label을 바꾸지 않는다" in prompt
    assert "적어도 하나를 보존하고 나머지만 누락" in prompt
    assert "DIFFERENT_BODY_TARGET을 DIFFERENT_ENDPOINT보다 우선" in prompt


def test_v3_prompt_blocks_generic_umbrella_false_positives() -> None:
    prompt = build_review_prompt(_review_frame(), rubric_version="v3")

    assert "일반적인 건강 상위어" in prompt
    assert "자외선 피부손상으로부터 피부건강 유지" in prompt
    assert "유해산소로부터 세포 보호" in prompt


def test_validated_decisions_fill_original_reviewer_order() -> None:
    filled = decisions_to_review_frame(
        _review_frame(),
        _response(),
        reviewer_id="anthropic:test-model",
    )

    assert filled["direction_id"].tolist() == ["direction-0", "direction-1"]
    assert filled["coverage_label"].tolist() == [
        "COVERS",
        "DOES_NOT_COVER",
    ]
    assert set(filled["reviewer_id"]) == {"anthropic:test-model"}


def test_v2_decision_accepts_broader_population_reason() -> None:
    review = _review_frame().iloc[:1].copy()
    response = json.dumps({
        "decisions": [{
            "direction_id": "direction-0",
            "coverage_label": "COVERS",
            "reason_code": "SAME_ENDPOINT_BROADER_POPULATION_OR_CONTEXT",
            "note": "같은 종점에서 대상 범위가 더 넓다.",
        }]
    }, ensure_ascii=False)

    filled = decisions_to_review_frame(
        review,
        response,
        reviewer_id="test",
        rubric_version="v2",
    )

    assert filled.at[0, "reason_code"] == (
        "SAME_ENDPOINT_BROADER_POPULATION_OR_CONTEXT"
    )


def test_rejects_missing_decision_or_wrong_reason_family() -> None:
    payload = json.loads(_response())
    payload["decisions"] = payload["decisions"][:1]
    with pytest.raises(ValueError, match="IDs do not match"):
        decisions_to_review_frame(
            _review_frame(),
            json.dumps(payload),
            reviewer_id="test",
        )


def test_label_only_keeps_label_and_blanks_mismatched_reason() -> None:
    review = _review_frame().iloc[:1].copy()
    response = json.dumps({
        "decisions": [{
            "direction_id": "direction-0",
            "coverage_label": "COVERS",
            "reason_code": "DIFFERENT_ENDPOINT",
            "note": "label과 reason이 충돌한다.",
        }],
    })

    result = decisions_to_review_frame(
        review,
        response,
        reviewer_id="model-a",
        rubric_version="v3",
        adjudication_scope="label-only",
    )

    assert result.at[0, "coverage_label"] == "COVERS"
    assert result.at[0, "reason_code"] == ""

    payload = json.loads(_response())
    payload["decisions"][0]["reason_code"] = "SAME_ENDPOINT_MECHANISM_DETAIL"
    with pytest.raises(ValueError, match="invalid LLM reason"):
        decisions_to_review_frame(
            _review_frame(),
            json.dumps(payload),
            reviewer_id="test",
        )


def _conflict_status() -> pd.DataFrame:
    return pd.DataFrame([{
        "direction_id": "direction-0",
        "source_claim_id": "source-0",
        "source_claim_text": "체지방 감소에 도움",
        "candidate_claim_id": "candidate-0",
        "candidate_claim_text": "과체중 성인의 체지방 감소에 도움",
        "reviewer_a_label": "COVERS",
        "reviewer_a_reason_code": "SAME_ENDPOINT_EQUIVALENT_WORDING",
        "reviewer_a_note": "같은 종점이다.",
        "reviewer_b_label": "DOES_NOT_COVER",
        "reviewer_b_reason_code": "CANDIDATE_SCOPE_NARROWER",
        "reviewer_b_note": "대상 인구가 좁다.",
        "agreement_status": "ADJUDICATION_REQUIRED",
        "final_coverage_label": "",
        "final_reason_code": "",
        "adjudicator_id": "",
        "adjudication_note": "",
    }])


def test_builds_and_applies_adjudication_without_sampling_metadata() -> None:
    status = _conflict_status()
    status["sampling_stratum"] = "hidden"
    prompt = build_adjudication_prompt(status)
    response = json.dumps({
        "decisions": [{
            "direction_id": "direction-0",
            "coverage_label": "DOES_NOT_COVER",
            "reason_code": "CANDIDATE_SCOPE_NARROWER",
            "note": "후보의 대상 인구가 더 좁다.",
        }]
    }, ensure_ascii=False)

    assert "hidden" not in prompt
    output = adjudications_to_status_frame(
        status,
        response,
        adjudicator_id="openai:test-model",
    )
    assert output.at[0, "agreement_status"] == "ADJUDICATED"
    assert output.at[0, "final_coverage_label"] == "DOES_NOT_COVER"
    assert output.at[0, "adjudicator_id"] == "openai:test-model"


def test_rejects_adjudication_for_wrong_conflict_id() -> None:
    response = json.dumps({
        "decisions": [{
            "direction_id": "different-direction",
            "coverage_label": "COVERS",
            "reason_code": "SAME_ENDPOINT_EQUIVALENT_WORDING",
            "note": "동등하다.",
        }]
    }, ensure_ascii=False)
    with pytest.raises(ValueError, match="IDs do not match"):
        adjudications_to_status_frame(
            _conflict_status(),
            response,
            adjudicator_id="openai:test-model",
        )
