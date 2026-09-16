"""고정 평가셋으로 현재 구현을 채점한다.

21절 「Seller Analysis 목표 지표」 를 실제로 재고, 채점기가 통과시키면 안 되는 것을
통과시키지 않는지도 본다.

⛔ 정답은 생성기가 세운 값이므로 이 채점은 순환하지 않는다.
"""

from __future__ import annotations

import csv
import json
import unittest
from pathlib import Path

from moongcheap_ai.seller_analysis.bid_guide import (
    METRICS_VERSION,
    ContractViolation,
    VersionMismatch,
    handle_bid_guide,
)
from moongcheap_ai.seller_analysis.evaluation.eval_set import (
    EVAL_FIELDS,
    GROUND_TRUTH_FIELDS,
    MIN_PARTICIPANTS,
    SCENARIO_QUOTA,
    GeneratorError,
    _exact_ratio,
    build_cases,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET_DIR = REPO_ROOT / "data" / "evaluation" / "seller_analysis"


def read_csv(name: str) -> list[dict[str, str]]:
    with (DATASET_DIR / name).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def as_request(row: dict[str, str]) -> dict:
    """평가 행을 계약 요청으로 바꾼다.

    평가 문서 16절의 입력 Schema 는 계산에 쓰이는 5개 값만 정의한다. 나머지 계약 필드는
    계산에 영향을 주지 않는 참조·버전 값이므로 여기서 고정값으로 채운다
    (16절 — *"실제 API Response의 최종 Field명은 Backend / AI API Contract와 동일하게 맞춘다"*).
    """
    payload = {
        "request_id": row["eval_id"],
        "input_context_version": "eval-context-v1",
        # 계산에 쓰이지 않는 참조값이다. 정수 계약이므로 eval_id 의 일련번호를 쓴다.
        "cluster_ref": int(row["eval_id"].rsplit("_", 1)[-1]),
        "product_ref": int(row["eval_id"].rsplit("_", 1)[-1]),
        "calculation_policy_version": METRICS_VERSION,
    }
    for field in (
        "participant_count",
        "total_demand_quantity",
        "minimum_success_quantity",
        "maximum_supply_quantity",
    ):
        payload[field] = int(row[field])

    overrides = json.loads(row["invalid_input_overrides"] or "{}")
    for field in overrides.get("remove", []):
        payload.pop(field, None)
    payload.update(overrides.get("set", {}))
    return payload


class EvalRunnerTest(unittest.TestCase):
    """실행기가 테스트와 같은 결론을 내는지 본다. 채점 경로가 둘로 갈리면 안 된다."""

    def test_runner_reports_every_target_met(self):
        from moongcheap_ai.seller_analysis.evaluation.runner import TARGETS, evaluate

        report = evaluate()
        self.assertEqual(report["case_count"], 100)
        self.assertEqual(report["failures"], [])
        self.assertTrue(report["all_targets_met"])
        for name in TARGETS:
            self.assertIn(name, report["metrics"], name)

    def test_runner_counts_invalid_cases_outside_numeric_accuracy(self):
        """18.1절 — Invalid Input Case 는 Numeric Accuracy 의 분모에서 제외한다."""
        from moongcheap_ai.seller_analysis.evaluation.runner import evaluate

        metrics = evaluate()["metrics"]
        self.assertEqual(metrics["numeric_accuracy"]["denominator"], 95)
        self.assertEqual(metrics["invalid_input_rejection_accuracy"]["denominator"], 5)

    def test_runner_does_not_build_its_own_answers(self):
        """⛔ 실행기가 정답을 계산하면 채점이 순환한다. 정답 CSV 만 읽어야 한다."""
        source = (
            Path(__file__).resolve().parents[2]
            / "src" / "moongcheap_ai" / "seller_analysis" / "evaluation" / "runner.py"
        ).read_text(encoding="utf-8")
        self.assertIn("GROUND_TRUTH_CSV", source)
        self.assertNotIn("build_cases", source)


class EvalSetScoringTest(unittest.TestCase):
    """평가셋으로 현재 구현을 채점한다. 21절 「Seller Analysis 목표 지표」 기준."""

    @classmethod
    def setUpClass(cls):
        eval_rows = {row["eval_id"]: row for row in read_csv("seller_analysis_eval_v1.csv")}
        cls.pairs = [
            (eval_rows[truth["eval_id"]], truth)
            for truth in read_csv("seller_analysis_ground_truth_v1.csv")
        ]

    def _responses(self):
        for row, truth in self.pairs:
            if truth["expected_request_result"] != "SUCCESS":
                continue
            yield truth, handle_bid_guide(as_request(row))["metrics"]

    def test_numeric_accuracy_is_100_percent(self):
        for truth, metrics in self._responses():
            with self.subTest(eval_id=truth["eval_id"]):
                self.assertEqual(
                    metrics["moq_attainment_ratio"],
                    float(truth["expected_moq_attainment_ratio"]),
                )
                self.assertEqual(
                    metrics["supply_coverage_ratio"],
                    float(truth["expected_supply_coverage_ratio"]),
                )

    def test_moq_and_supply_status_accuracy_are_100_percent(self):
        """상태는 응답에 없다. 계약대로 **비율에서 도출**해 채점한다.

        「AI API Contract」 5절 Response 표가 `metrics` 를 네 필드로 정하므로 상태 필드는
        응답에 싣지 않는다. `ratio >= 1.0` 이 충족과 동치라는 것이 이 채점의 전제다.
        """
        for truth, metrics in self._responses():
            with self.subTest(eval_id=truth["eval_id"]):
                derived_moq = (
                    "MOQ_MET" if metrics["moq_attainment_ratio"] >= 1.0 else "MOQ_NOT_MET"
                )
                derived_supply = (
                    "SUPPLY_SUFFICIENT"
                    if metrics["supply_coverage_ratio"] >= 1.0
                    else "SUPPLY_INSUFFICIENT"
                )
                self.assertEqual(derived_moq, truth["expected_moq_status"])
                self.assertEqual(derived_supply, truth["expected_supply_status"])

    def test_invalid_input_rejection_accuracy_is_100_percent(self):
        for row, truth in self.pairs:
            if truth["expected_request_result"] != "REJECTED":
                continue
            with self.subTest(eval_id=truth["eval_id"]):
                with self.assertRaises((ContractViolation, VersionMismatch)):
                    handle_bid_guide(as_request(row))

    def test_no_individual_consumer_value_reaches_the_response(self):
        """20절 「개인정보 안전성 평가」 — PII Leakage Rate 0%."""
        for row, truth in self.pairs:
            if truth["expected_request_result"] != "SUCCESS":
                continue
            body = json.dumps(handle_bid_guide(as_request(row)), ensure_ascii=False)
            for leaked in ("member_id", "user_id", "buyer_id", "MEMBER_"):
                self.assertNotIn(leaked, body)

    def test_evidence_never_contradicts_the_status(self):
        """18.4절 Evidence Consistency — 설명과 구조화 결과가 어긋나지 않는다."""
        for row, truth in self.pairs:
            if truth["expected_request_result"] != "SUCCESS":
                continue
            result = handle_bid_guide(as_request(row))
            evidence = " ".join(result["calculation_evidence"])
            with self.subTest(eval_id=truth["eval_id"]):
                self.assertIn(truth["expected_moq_status"], evidence)
                self.assertIn(truth["expected_supply_status"], evidence)


class EvalRunnerRigourTest(unittest.TestCase):
    """B4 — 실행기가 통과시키면 안 되는 것들을 통과시켰다."""

    def _report_with_body(self, mutate):
        from unittest import mock

        from moongcheap_ai.seller_analysis.evaluation import runner

        original = runner.handle_bid_guide

        def patched(payload):
            body = original(payload)
            mutate(body)
            return body

        with mock.patch.object(runner, "handle_bid_guide", side_effect=patched):
            return runner.evaluate()

    def test_wrong_type_fails_schema_validation(self):
        """계약은 `analysis_reason` 을 string 으로 정한다. 정수 123 은 통과하면 안 된다.

        키 집합만 비교하던 검사는 이것을 95/95 로 통과시켰다.
        """
        def to_integer(body):
            body["analysis_reason"] = 123

        report = self._report_with_body(to_integer)
        self.assertEqual(report["metrics"]["response_schema_validation_success"]["count"], 0)
        self.assertFalse(report["all_targets_met"])

    def test_out_of_range_value_fails_schema_validation(self):
        """`minimum` 도 계약이다. 음수 비율은 구조가 맞아도 계약 위반이다."""
        def negative_ratio(body):
            body["metrics"]["moq_attainment_ratio"] = -1.0

        report = self._report_with_body(negative_ratio)
        self.assertEqual(report["metrics"]["response_schema_validation_success"]["count"], 0)

    def test_extra_sentence_fails_evidence_consistency(self):
        """계약은 근거를 *"템플릿으로만"* 만들라고 한다. 덧붙은 문장은 템플릿이 아니다."""
        def append_sentence(body):
            body["calculation_evidence"].append("검증용 모순 문장: 모든 수량 계산은 잘못됐습니다.")

        report = self._report_with_body(append_sentence)
        self.assertEqual(report["metrics"]["evidence_consistency"]["count"], 0)
        self.assertFalse(report["all_targets_met"])

    def test_empty_dataset_is_not_a_pass(self):
        """⛔ 채점하지 못한 것은 통과가 아니다. `all([])` 이 참이라는 사실에 기대지 않는다."""
        from unittest import mock

        from moongcheap_ai.seller_analysis.evaluation import runner

        with mock.patch.object(runner, "read_csv", return_value=[]):
            report = runner.evaluate()
        self.assertEqual(report["case_count"], 0)
        self.assertFalse(report["all_targets_met"])
        self.assertTrue(report["unmeasured_metrics"])

    def test_validator_refuses_keywords_it_does_not_implement(self):
        """계약에 새 키워드가 생기면 조용히 넘어가지 않고 멈춘다."""
        from moongcheap_ai.seller_analysis.evaluation.runner import validate_against_schema

        with self.assertRaises(NotImplementedError):
            validate_against_schema("x", {"type": "string", "pattern": "^x$"})


class NumericToleranceTest(unittest.TestCase):
    """18.1절이 *"사전에 정한 허용 오차"* 를 요구한다. 그 값을 못박는다."""

    def test_tolerance_is_far_below_the_declared_precision(self):
        """⛔ 자리수를 허용 오차로 쓰면 그 자리수 명세가 무의미해진다.

        계약이 비율을 소수 4자리로 두므로(`numeric(5,4)`) 허용 오차가 1e-4 면
        마지막 자리가 통째로 덮인다. 표현 오차만 흡수하는 폭이어야 한다.
        """
        from moongcheap_ai.seller_analysis.bid_guide import RATIO_PRECISION
        from moongcheap_ai.seller_analysis.evaluation.runner import NUMERIC_TOLERANCE

        self.assertLess(NUMERIC_TOLERANCE, 10 ** -RATIO_PRECISION / 1000)

    def test_tolerance_does_not_hide_a_real_error(self):
        """마지막 자리 한 칸이 틀리면 잡아야 한다."""
        from unittest import mock

        from moongcheap_ai.seller_analysis.evaluation import runner

        original = runner.handle_bid_guide

        def off_by_one_ulp(payload):
            body = original(payload)
            body["metrics"]["moq_attainment_ratio"] += 10 ** -runner.__dict__.get("RATIO", 4)
            return body

        with mock.patch.object(runner, "handle_bid_guide", side_effect=off_by_one_ulp):
            report = runner.evaluate()
        self.assertEqual(report["metrics"]["numeric_accuracy"]["count"], 0)

    def test_report_records_the_tolerance_it_used(self):
        from moongcheap_ai.seller_analysis.evaluation.runner import NUMERIC_TOLERANCE, evaluate

        self.assertEqual(evaluate()["numeric_tolerance"], NUMERIC_TOLERANCE)


class EvidenceNumberTest(unittest.TestCase):
    """근거 문장의 **숫자**가 실제 입력·계산 결과와 같은지 본다.

    형태만 보는 검사는 2026-09-11 재현에서 수량을 `999999` 로 바꿔도 66/95 를 줬다.
    """

    def test_tampered_numbers_fail_evidence_consistency(self):
        import re
        from unittest import mock

        from moongcheap_ai.seller_analysis.evaluation import runner

        original = runner.handle_bid_guide

        def tampered(payload):
            body = original(payload)
            body["calculation_evidence"] = [
                re.sub(r"\d+", "999999", line) for line in body["calculation_evidence"]
            ]
            return body

        with mock.patch.object(runner, "handle_bid_guide", side_effect=tampered):
            report = runner.evaluate()
        entry = report["metrics"]["evidence_consistency"]
        self.assertEqual(entry["count"], 0)
        self.assertEqual(entry["denominator"], 95)

    def test_single_digit_change_fails_evidence_consistency(self):
        """한 건, 한 자리만 바꿔도 그 한 건이 실패해야 한다."""
        from unittest import mock

        from moongcheap_ai.seller_analysis.evaluation import runner

        original = runner.handle_bid_guide

        def bumped(payload):
            body = original(payload)
            if payload["request_id"] == "SELLER_EVAL_002":
                body["calculation_evidence"][0] = body["calculation_evidence"][0].replace(
                    "총수요 ", "총수요 1", 1
                )
            return body

        with mock.patch.object(runner, "handle_bid_guide", side_effect=bumped):
            report = runner.evaluate()
        self.assertEqual(report["metrics"]["evidence_consistency"]["count"], 94)

    def test_expected_sentences_come_from_the_dataset(self):
        """기대 문장은 평가셋·정답만으로 만든다 — 구현을 부르지 않는다."""
        from unittest import mock

        from moongcheap_ai.seller_analysis.evaluation import runner

        row = {
            "total_demand_quantity": "130",
            "minimum_success_quantity": "100",
            "maximum_supply_quantity": "150",
        }
        truth = {
            "expected_moq_attainment_ratio": "1.3",
            "expected_supply_coverage_ratio": "1.0",
            "expected_moq_status": "MOQ_MET",
            "expected_supply_status": "SUPPLY_SUFFICIENT",
        }
        with mock.patch.object(runner, "handle_bid_guide", side_effect=AssertionError):
            lines = runner.expected_evidence(row, truth)
        # 「AI API Contract」 5절 「Seller Analysis API」 의 상한 예시 문장 그대로다.
        self.assertEqual(
            lines[1],
            "판매자 최대 공급 가능 수량 150개를 총수요 130개로 나눈 결과는 "
            "약 1.15이며, 계산 정책의 상한 1.0을 적용했습니다.",
        )


class SchemaFirstTest(unittest.TestCase):
    """계약을 벗어난 응답 한 건이 나머지 94건의 채점을 막지 않아야 한다."""

    def _evaluate_with(self, broken):
        from unittest import mock

        from moongcheap_ai.seller_analysis.evaluation import runner

        original = runner.handle_bid_guide

        def patched(payload):
            return broken(original(payload))

        with mock.patch.object(runner, "handle_bid_guide", side_effect=patched):
            return runner.evaluate()

    def test_missing_metrics_is_recorded_not_raised(self):
        def drop(body):
            body.pop("metrics")
            return body

        report = self._evaluate_with(drop)
        self.assertEqual(report["metrics"]["response_schema_validation_success"]["count"], 0)
        self.assertEqual(report["metrics"]["numeric_accuracy"]["count"], 0)
        self.assertFalse(report["all_targets_met"])

    def test_string_ratio_is_recorded_not_raised(self):
        def stringify(body):
            body["metrics"]["supply_coverage_ratio"] = str(body["metrics"]["supply_coverage_ratio"])
            return body

        report = self._evaluate_with(stringify)
        self.assertEqual(report["metrics"]["response_schema_validation_success"]["count"], 0)
        self.assertFalse(report["all_targets_met"])

    def test_broken_case_stays_in_every_denominator(self):
        """⛔ 채점하지 못한 건을 분모에서 빼면 정확도가 **올라간다.**"""

        def break_one(body):
            if body["request_id"] == "SELLER_EVAL_002":
                body.pop("metrics")
            return body

        report = self._evaluate_with(break_one)
        for name in (
            "numeric_accuracy",
            "moq_status_accuracy",
            "supply_status_accuracy",
            "evidence_consistency",
            "response_schema_validation_success",
        ):
            entry = report["metrics"][name]
            self.assertEqual(entry["denominator"], 95, name)
            self.assertEqual(entry["count"], 94, name)
        self.assertFalse(report["all_targets_met"])


class EchoFieldTest(unittest.TestCase):
    """`metrics` 의 네 필드와 요청 참조가 요청값을 그대로 되돌려 주는지 본다.

    비율 두 개만 보던 시절에는 나머지를 아무 값으로 바꿔도 95/95 였다.
    """

    def _numeric_count(self, broken):
        from unittest import mock

        from moongcheap_ai.seller_analysis.evaluation import runner

        original = runner.handle_bid_guide

        with mock.patch.object(
            runner, "handle_bid_guide", side_effect=lambda payload: broken(original(payload))
        ):
            return runner.evaluate()["metrics"]["numeric_accuracy"]["count"]

    def test_wrong_participant_count_fails(self):
        def tamper(body):
            body["metrics"]["participant_count"] = 999
            return body

        self.assertEqual(self._numeric_count(tamper), 0)

    def test_wrong_total_demand_quantity_fails(self):
        def tamper(body):
            body["metrics"]["total_demand_quantity"] = 999
            return body

        self.assertLessEqual(self._numeric_count(tamper), 1)

    def test_response_for_another_request_fails(self):
        """⛔ 다른 요청의 결과라면 숫자가 맞아도 맞은 것이 아니다."""

        def tamper(body):
            body["request_id"] = "SELLER_EVAL_999"
            return body

        self.assertEqual(self._numeric_count(tamper), 0)

    def test_wrong_input_context_version_fails(self):
        def tamper(body):
            body["input_context_version"] = "eval-context-v9"
            return body

        self.assertEqual(self._numeric_count(tamper), 0)


class AnalysisReasonTest(unittest.TestCase):
    """계약이 AI 에게 맡긴 판단 사유 한 문장도 채점 대상이다."""

    def test_unsupported_claim_fails_evidence_consistency(self):
        """「AI 아키텍처 및 안전성 정책 초안」 24절이 금지한 확정적 예측."""
        from unittest import mock

        from moongcheap_ai.seller_analysis.evaluation import runner

        original = runner.handle_bid_guide

        def tamper(payload):
            body = original(payload)
            body["analysis_reason"] = "이 가격이면 반드시 판매에 성공합니다."
            return body

        with mock.patch.object(runner, "handle_bid_guide", side_effect=tamper):
            report = runner.evaluate()
        self.assertEqual(report["metrics"]["evidence_consistency"]["count"], 0)

    def test_reason_of_the_opposite_status_fails(self):
        """근거 세 줄이 멀쩡해도 사유가 반대 상태를 말하면 모순이다."""
        from unittest import mock

        from moongcheap_ai.seller_analysis.evaluation import runner

        original = runner.handle_bid_guide

        def tamper(payload):
            body = original(payload)
            body["analysis_reason"] = runner.REASON_TEMPLATES[False, False]
            return body

        with mock.patch.object(runner, "handle_bid_guide", side_effect=tamper):
            report = runner.evaluate()
        # (False, False) 가 정답인 Case 만 남는다.
        self.assertLess(report["metrics"]["evidence_consistency"]["count"], 95)


class SchemaPreflightTest(unittest.TestCase):
    """스키마는 **값이 닿기 전에** 전부 훑는다."""

    def test_unknown_keyword_on_an_unvisited_branch_is_caught(self):
        """⛔ 빈 배열의 `items` 가지는 한 번도 걸어 보지 않는다. 그래도 잡아야 한다."""
        import copy

        from moongcheap_ai.seller_analysis.evaluation.runner import (
            RESPONSE_SCHEMA,
            validate_against_schema,
        )

        schema = copy.deepcopy(json.loads(RESPONSE_SCHEMA.read_text(encoding="utf-8")))
        schema["properties"]["unresolved_items"]["items"]["pattern"] = "^X"
        body = {
            "request_id": "X",
            "input_context_version": "X",
            "metrics": {
                "participant_count": 1,
                "total_demand_quantity": 1,
                "moq_attainment_ratio": 1.0,
                "supply_coverage_ratio": 1.0,
            },
            "analysis_reason": "X",
            "calculation_evidence": ["X"],
            "unresolved_items": [],
            "calculation_policy_version": "seller-metrics-v1",
        }
        with self.assertRaises(NotImplementedError):
            validate_against_schema(body, schema)

    def test_non_finite_number_fails_schema_validation(self):
        """⛔ `inf` 는 어떤 `minimum` 도 통과한다. JSON 에 없는 값이다."""
        from unittest import mock

        from moongcheap_ai.seller_analysis.evaluation import runner

        original = runner.handle_bid_guide

        def tamper(payload):
            body = original(payload)
            body["metrics"]["supply_coverage_ratio"] = float("inf")
            return body

        with mock.patch.object(runner, "handle_bid_guide", side_effect=tamper):
            report = runner.evaluate()
        self.assertEqual(report["metrics"]["response_schema_validation_success"]["count"], 0)


class DatasetIntegrityTest(unittest.TestCase):
    """평가셋과 정답이 서로 맞는 짝인지 채점 전에 본다.

    2026-09-11 재현 — 양쪽에 첫 행을 하나씩 더 붙이면 101건인데 전 지표 목표 달성이었다.
    """

    def setUp(self):
        from moongcheap_ai.seller_analysis.evaluation.runner import (
            EVAL_CSV,
            GROUND_TRUTH_CSV,
            read_csv,
        )

        self.inputs = read_csv(EVAL_CSV)
        self.truths = read_csv(GROUND_TRUTH_CSV)

    def test_frozen_dataset_is_a_matching_pair(self):
        from moongcheap_ai.seller_analysis.evaluation.runner import dataset_integrity_errors

        self.assertEqual(dataset_integrity_errors(self.inputs, self.truths), [])

    def test_duplicate_id_is_reported(self):
        from moongcheap_ai.seller_analysis.evaluation.runner import dataset_integrity_errors

        errors = dataset_integrity_errors(
            self.inputs + [self.inputs[0]], self.truths + [self.truths[0]]
        )
        self.assertEqual(len(errors), 2)
        self.assertTrue(all("중복" in line for line in errors))

    def test_missing_truth_row_is_reported(self):
        from moongcheap_ai.seller_analysis.evaluation.runner import dataset_integrity_errors

        self.assertTrue(dataset_integrity_errors(self.inputs, self.truths[:-1]))

    def test_extra_truth_row_is_reported(self):
        from moongcheap_ai.seller_analysis.evaluation.runner import dataset_integrity_errors

        extra = dict(self.truths[0], eval_id="SELLER_EVAL_999")
        self.assertTrue(dataset_integrity_errors(self.inputs, self.truths + [extra]))

    def test_broken_dataset_never_reports_a_pass(self):
        """⛔ 짝이 어긋난 채로는 한 건도 채점하지 않고, 통과로도 보고하지 않는다."""
        from unittest import mock

        from moongcheap_ai.seller_analysis.evaluation import runner

        original = runner.read_csv

        def duplicated(path):
            rows = original(path)
            return rows + [rows[0]]

        with mock.patch.object(runner, "read_csv", side_effect=duplicated):
            report = runner.evaluate()

        self.assertTrue(report["dataset_integrity_errors"])
        self.assertFalse(report["all_targets_met"])
        self.assertEqual(report["case_count"], 0)
        self.assertEqual(sorted(report["unmeasured_metrics"]), sorted(report["metrics"]))

    def test_integrity_check_does_not_hardcode_the_v1_shape(self):
        """⛔ 건수·분포를 박으면 골드셋을 버전별로 못 늘린다 (정의서 26절)."""
        from moongcheap_ai.seller_analysis.evaluation.runner import dataset_integrity_errors

        small = [dict(self.inputs[0], eval_id="OTHER_SET_001")]
        small_truth = [dict(self.truths[0], eval_id="OTHER_SET_001")]
        self.assertEqual(dataset_integrity_errors(small, small_truth), [])


class V29RegressionTest(unittest.TestCase):
    """2026-09-11 교차검토에서 나온 반례를 고정한다.

    전부 「검사가 있었고, 통과하고 있었고, 검사 대상을 보고 있지 않았다」는 같은 형태다.
    """

    def _evaluate(self, patch):
        from unittest import mock

        from moongcheap_ai.seller_analysis.evaluation import runner

        original = runner.handle_bid_guide
        with mock.patch.object(
            runner, "handle_bid_guide", side_effect=lambda payload: patch(original, payload)
        ):
            return runner.evaluate()

    def test_boundary_ratio_does_not_falsely_expect_the_cap_sentence(self):
        """⛔ 정수로는 초과지만 비율은 상한에 닿지 않는 경계.

        `supply > demand` 로 분기하면 **올바른 구현을 실패로 찍는다.**
        """
        from moongcheap_ai.seller_analysis.bid_guide import handle_bid_guide
        from moongcheap_ai.seller_analysis.evaluation.runner import (
            EVAL_CONTEXT_VERSION,
            METRICS_VERSION,
            expected_evidence,
        )

        demand, supply = 100_000, 100_001
        body = handle_bid_guide(
            {
                "request_id": "BOUNDARY",
                "input_context_version": EVAL_CONTEXT_VERSION,
                "cluster_ref": 1,
                "product_ref": 1,
                "calculation_policy_version": METRICS_VERSION,
                "participant_count": 1,
                "total_demand_quantity": demand,
                "minimum_success_quantity": 1,
                "maximum_supply_quantity": supply,
            }
        )
        wanted = expected_evidence(
            {
                "total_demand_quantity": str(demand),
                "minimum_success_quantity": "1",
                "maximum_supply_quantity": str(supply),
            },
            {
                "expected_moq_attainment_ratio": str(float(demand)),
                "expected_supply_coverage_ratio": "1.0",
                "expected_moq_status": "MOQ_MET",
                "expected_supply_status": "SUPPLY_SUFFICIENT",
            },
        )
        self.assertEqual(body["calculation_evidence"], wanted)
        self.assertNotIn("상한", wanted[1])

    def test_non_numeric_ground_truth_stops_scoring(self):
        """⛔ 정답이 NaN 이면 `abs(got - want) > tol` 이 항상 거짓이다."""
        from unittest import mock

        from moongcheap_ai.seller_analysis.evaluation import runner

        original = runner.read_csv

        def nan_truth(path):
            rows = original(path)
            if "ground_truth" in path.name:
                for row in rows:
                    row["expected_moq_attainment_ratio"] = "nan"
            return rows

        with mock.patch.object(runner, "read_csv", side_effect=nan_truth):
            report = runner.evaluate()

        self.assertTrue(report["dataset_integrity_errors"])
        self.assertFalse(report["all_targets_met"])
        self.assertEqual(report["metrics"]["numeric_accuracy"]["denominator"], 0)

    def test_handler_cannot_pass_by_mutating_the_request(self):
        """⛔ 기준이 payload 면 구현이 payload 를 고쳐 놓고 맞췄다고 할 수 있다."""

        def mutate(original, payload):
            body = original(payload)
            payload["participant_count"] = 999
            body["metrics"]["participant_count"] = 999
            return body

        report = self._evaluate(mutate)
        self.assertEqual(report["metrics"]["numeric_accuracy"]["count"], 0)
        self.assertFalse(report["all_targets_met"])

    def test_wrongful_rejection_shrinks_no_denominator(self):
        """⛔ 한 지표만 실패로 적으면 나머지 분모가 줄어 정확도가 부풀려진다."""
        from unittest import mock

        from moongcheap_ai.seller_analysis.evaluation import runner
        from moongcheap_ai.seller_analysis.bid_guide import ContractViolation

        original = runner.handle_bid_guide

        def wrongly_reject(payload):
            if payload["request_id"] == "SELLER_EVAL_002":
                raise ContractViolation("정상인데 거절")
            return original(payload)

        with mock.patch.object(runner, "handle_bid_guide", side_effect=wrongly_reject):
            report = runner.evaluate()

        for name in runner.SCORED_ON_SUCCESS:
            entry = report["metrics"][name]
            self.assertEqual(entry["denominator"], 95, name)
            self.assertEqual(entry["count"], 94, name)

    def test_unresolved_items_content_is_checked(self):
        """네 수량이 모두 주어진 Case 이므로 계산 못 한 항목이 없어야 한다."""

        def add_claim(original, payload):
            body = original(payload)
            body["unresolved_items"] = ["이 가격이면 반드시 판매에 성공합니다."]
            return body

        report = self._evaluate(add_claim)
        self.assertEqual(report["metrics"]["evidence_consistency"]["count"], 0)
        self.assertFalse(report["all_targets_met"])

    def test_schema_valued_additional_properties_is_refused(self):
        """⛔ 선순회가 「다 안다」고 해 놓고 검사하지 않으면 그게 더 나쁘다."""
        from moongcheap_ai.seller_analysis.evaluation.runner import validate_against_schema

        with self.assertRaises(NotImplementedError):
            validate_against_schema(
                {"a": "x", "b": 123},
                {
                    "type": "object",
                    "properties": {"a": {"type": "string"}},
                    "additionalProperties": {"type": "string"},
                },
            )


class ArtifactHashTest(unittest.TestCase):
    """같은 버전 이름이 같은 내용을 가리키는지 리포트로 확인할 수 있어야 한다."""

    def test_report_records_every_input_that_changes_the_result(self):
        from moongcheap_ai.seller_analysis.evaluation.runner import evaluate

        digests = evaluate()["artifact_sha256"]
        # 데이터만 고정해서는 재현되지 않는다. 채점 규칙과 계산 구현도 결과를 바꾼다.
        self.assertEqual(
            sorted(digests),
            ["calculator", "eval_csv", "ground_truth_csv", "response_schema", "runner"],
        )
        for name, value in digests.items():
            self.assertRegex(value, r"^[0-9a-f]{64}$", name)

    def test_same_version_name_with_different_content_is_visible(self):
        """⛔ 축소한 평가셋도 `dataset_version` 은 그대로다. 해시가 그 차이를 드러낸다."""
        from unittest import mock

        from moongcheap_ai.seller_analysis.evaluation import runner

        full = runner.evaluate()
        original = runner.read_csv
        with mock.patch.object(
            runner, "read_csv", side_effect=lambda p: original(p)[:5] + original(p)[-5:]
        ):
            clipped = runner.evaluate()

        # 버전 문자열은 같다 — 그래서 해시가 필요하다.
        self.assertEqual(full["dataset_version"], clipped["dataset_version"])
        self.assertNotEqual(full["case_count"], clipped["case_count"])
        # 파일 자체는 건드리지 않았으므로 해시는 같다. 해시는 **파일**의 동일성을 말한다.
        self.assertEqual(full["artifact_sha256"], clipped["artifact_sha256"])
