"""판매자 수요 분석 계약 회귀.

FastAPI 없이 도는 검사만 둔다. 계산과 계약이 전송 계층과 분리돼 있는지도 함께 본다.
기준 문서 — 「AI–Backend 판매자 수요 분석 연동 API 기능 요구 명세서(협의안)」 5절.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from moongcheap_ai.seller_analysis.bid_guide import (
    METRICS_VERSION,
    SUPPORTED_POLICY_VERSIONS,
    BidGuideRequest,
    ContractViolation,
    VersionMismatch,
    build_bid_guide,
    handle_bid_guide,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = REPO_ROOT / "docs" / "contracts"


def valid_payload(**overrides):
    payload = {
        "request_id": "seller-analysis-request-001",
        "input_context_version": "demand-context-008",
        "cluster_ref": 1000001,
        "product_ref": 4210,
        "participant_count": 13,
        "total_demand_quantity": 130,
        "minimum_success_quantity": 100,
        "maximum_supply_quantity": 150,
        "calculation_policy_version": METRICS_VERSION,
    }
    payload.update(overrides)
    return payload


class BidGuideContractTest(unittest.TestCase):
    def test_documented_example_reproduces_the_documented_numbers(self):
        result = handle_bid_guide(valid_payload())
        metrics = result["metrics"]
        self.assertEqual(metrics["participant_count"], 13)
        self.assertEqual(metrics["total_demand_quantity"], 130)
        self.assertEqual(metrics["moq_attainment_ratio"], 1.3)
        self.assertEqual(result["calculation_policy_version"], METRICS_VERSION)

    def test_metrics_carries_exactly_the_four_contract_fields(self):
        """⛔ 「AI API Contract」 5절 Response 표가 나열한 넷이다. 상태를 넣지 않는다."""
        self.assertEqual(
            set(handle_bid_guide(valid_payload())["metrics"]),
            {
                "participant_count",
                "total_demand_quantity",
                "moq_attainment_ratio",
                "supply_coverage_ratio",
            },
        )

    def test_status_stays_derivable_from_the_ratio(self):
        """상태를 응답에서 뺐으므로 `ratio >= 1.0` 동치가 깨지면 되살릴 수 없다."""
        for demand, moq, supply, moq_met, supply_met in [
            (130, 100, 150, True, True),
            (99, 100, 99, False, True),
            (999, 1000, 1000, False, True),
            (1000, 1000, 999, True, False),
            (100, 100, 100, True, True),
        ]:
            with self.subTest(demand=demand, moq=moq, supply=supply):
                metrics = handle_bid_guide(
                    valid_payload(
                        total_demand_quantity=demand,
                        minimum_success_quantity=moq,
                        maximum_supply_quantity=supply,
                    )
                )["metrics"]
                self.assertEqual(metrics["moq_attainment_ratio"] >= 1.0, moq_met)
                self.assertEqual(metrics["supply_coverage_ratio"] >= 1.0, supply_met)

    def test_metrics_are_nested_not_flattened(self):
        """평면으로 펴면 RAG API 가 Required 로 받는 입력 구조까지 깨진다(명세서 4.5절)."""
        result = handle_bid_guide(valid_payload())
        self.assertIsInstance(result["metrics"], dict)
        for leaked in ("moq_attainment_ratio", "supply_coverage_ratio", "participant_count"):
            self.assertNotIn(leaked, result)

    def test_top_level_shape_is_the_documented_six_fields(self):
        self.assertEqual(
            set(handle_bid_guide(valid_payload())),
            {
                "request_id",
                "input_context_version",
                "metrics",
                "analysis_reason",
                "calculation_evidence",
                "unresolved_items",
                "calculation_policy_version",
            },
        )

    def test_same_input_always_gives_the_same_result(self):
        self.assertEqual(handle_bid_guide(valid_payload()), handle_bid_guide(valid_payload()))

    def test_moq_shortfall_is_reported_not_rounded_away(self):
        result = handle_bid_guide(valid_payload(total_demand_quantity=99))
        self.assertLess(result["metrics"]["moq_attainment_ratio"], 1.0)
        self.assertIn("MOQ_NOT_MET", " ".join(result["calculation_evidence"]))

    def test_ratio_never_reads_as_met_when_status_is_not_met(self):
        """999/1000이 1.00으로 보이면 숫자와 판정이 서로 반대가 된다."""
        result = handle_bid_guide(
            valid_payload(
                total_demand_quantity=999,
                minimum_success_quantity=1000,
                maximum_supply_quantity=1000,
            )
        )
        self.assertLess(result["metrics"]["moq_attainment_ratio"], 1.0)
        self.assertNotIn("결과는 1.00입니다", result["calculation_evidence"][0])

    def test_supply_ratio_never_reads_as_sufficient_when_it_is_not(self):
        result = handle_bid_guide(
            valid_payload(
                total_demand_quantity=1000,
                minimum_success_quantity=1000,
                maximum_supply_quantity=999,
            )
        )
        self.assertLess(result["metrics"]["supply_coverage_ratio"], 1.0)
        self.assertNotIn("결과는 1.00입니다", result["calculation_evidence"][1])

    def test_supply_shortfall_is_reported(self):
        result = handle_bid_guide(valid_payload(maximum_supply_quantity=100))
        self.assertLess(result["metrics"]["supply_coverage_ratio"], 1.0)
        self.assertIn("SUPPLY_INSUFFICIENT", " ".join(result["calculation_evidence"]))

    def test_individual_consumer_fields_are_refused_not_dropped(self):
        for field in ("member_ids", "individual_budget", "user_id", "requested_quantities"):
            with self.subTest(field=field):
                with self.assertRaises(ContractViolation):
                    handle_bid_guide(valid_payload(**{field: "PRIVATE_SENTINEL"}))

    def test_round_ref_is_no_longer_accepted(self):
        """2026-09-09 Backend 회신 — *"현재 구현하지 않을 기능"*. 계약에서 뺐다."""
        with self.assertRaises(ContractViolation):
            handle_bid_guide(valid_payload(round_ref="seller-round-018"))

    def test_reference_ids_must_be_integers(self):
        """*"id인 만큼 정수로 표기 부탁드립니다"* — 2026-09-09 Backend 회신."""
        for field in ("cluster_ref", "product_ref"):
            for bad in ("cluster-027", 0, -1, 1.5, True, None):
                with self.subTest(field=field, bad=bad):
                    with self.assertRaises(ContractViolation):
                        handle_bid_guide(valid_payload(**{field: bad}))

    def test_analysis_reason_states_both_observed_conditions(self):
        """⛔ 입력에 없는 사실과 확정적 예측을 담지 않는다 (아키텍처 초안 24절)."""
        met = handle_bid_guide(valid_payload())["analysis_reason"]
        self.assertIn("충족", met)
        short = handle_bid_guide(valid_payload(total_demand_quantity=90,
                                               maximum_supply_quantity=90))["analysis_reason"]
        self.assertIn("미치지 못", short)
        for banned in ("반드시", "성공", "추천", "20대", "여성", "예상"):
            for text in (met, short):
                self.assertNotIn(banned, text)

    def test_analysis_reason_is_deterministic(self):
        """템플릿이므로 같은 입력이면 같은 문장이다. 생성 모델을 쓰지 않는다."""
        self.assertEqual(
            handle_bid_guide(valid_payload())["analysis_reason"],
            handle_bid_guide(valid_payload())["analysis_reason"],
        )

    def test_unknown_and_missing_fields_are_refused(self):
        with self.assertRaises(ContractViolation):
            handle_bid_guide(valid_payload(uncontracted="x"))
        short = valid_payload()
        del short["cluster_ref"]
        with self.assertRaises(ContractViolation):
            handle_bid_guide(short)

    def test_calculation_policy_version_is_required(self):
        """계약의 Required 필드다. 없으면 계약 위반이다."""
        without = valid_payload()
        del without["calculation_policy_version"]
        with self.assertRaises(ContractViolation):
            handle_bid_guide(without)

    def test_unsupported_policy_version_is_refused_as_version_mismatch(self):
        """AI 는 버전을 발급하지 않고 검증만 한다(명세서 4.2절)."""
        with self.assertRaises(VersionMismatch):
            handle_bid_guide(valid_payload(calculation_policy_version="seller-metrics-v999"))

    def test_version_mismatch_is_not_a_contract_violation(self):
        """⛔ 하위형이면 전송 계층에서 먼저 걸리는 쪽에 따라 오류 코드가 뒤바뀐다."""
        self.assertFalse(issubclass(VersionMismatch, ContractViolation))
        self.assertFalse(issubclass(ContractViolation, VersionMismatch))

    def test_blank_policy_version_is_a_contract_violation_not_a_mismatch(self):
        """형식 검사가 먼저다. 빈 문자열은 버전 불일치가 아니라 형식 오류다."""
        with self.assertRaises(ContractViolation):
            handle_bid_guide(valid_payload(calculation_policy_version="   "))

    def test_supported_policy_versions_include_the_implemented_one(self):
        self.assertIn(METRICS_VERSION, SUPPORTED_POLICY_VERSIONS)

    def test_response_echoes_the_requested_policy_version(self):
        result = handle_bid_guide(valid_payload())
        self.assertEqual(result["calculation_policy_version"], METRICS_VERSION)

    def test_quantities_are_not_silently_coerced(self):
        for value in (0, -1, 12.5, "130", True, None):
            with self.subTest(value=value):
                with self.assertRaises(ContractViolation):
                    handle_bid_guide(valid_payload(total_demand_quantity=value))

    def test_non_object_payloads_are_refused(self):
        for payload in (None, [], "request", 30):
            with self.subTest(payload=payload):
                with self.assertRaises(ContractViolation):
                    handle_bid_guide(payload)

    def test_response_matches_the_declared_contract(self):
        schema = json.loads(
            (CONTRACTS / "seller_bid_guide_response_v01.schema.json").read_text(encoding="utf-8")
        )
        result = handle_bid_guide(valid_payload())
        self.assertEqual(set(result), set(schema["properties"]))
        self.assertEqual(set(result), set(schema["required"]))
        metrics_schema = schema["properties"]["metrics"]
        self.assertEqual(set(result["metrics"]), set(metrics_schema["properties"]))
        self.assertEqual(set(result["metrics"]), set(metrics_schema["required"]))
        self.assertEqual(
            result["calculation_policy_version"],
            schema["properties"]["calculation_policy_version"]["const"],
        )

    def test_request_schema_matches_the_accepted_fields(self):
        schema = json.loads(
            (CONTRACTS / "seller_bid_guide_request_v01.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(set(schema["properties"]), set(valid_payload()))
        self.assertEqual(set(schema["required"]), set(valid_payload()))

    def test_evidence_only_restates_computed_numbers(self):
        result = handle_bid_guide(valid_payload())
        joined = " ".join(result["calculation_evidence"])
        for number in ("130", "100", "150", "1.30", "1.15"):
            self.assertIn(number, joined)

    def test_unresolved_items_is_present_and_empty_when_everything_computes(self):
        """비어 있어도 키는 나간다. 없으면 Backend 가 필드 부재와 미해결을 구분할 수 없다."""
        result = handle_bid_guide(valid_payload())
        self.assertEqual(result["unresolved_items"], [])

    def test_contract_logic_does_not_need_the_transport_layer(self):
        """계산은 FastAPI 없이 돌아야 한다."""
        import moongcheap_ai.seller_analysis.bid_guide as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("import ") or stripped.startswith("from "):
                self.assertNotIn("fastapi", stripped.lower(), stripped)
        self.assertIsInstance(build_bid_guide(BidGuideRequest.from_dict(valid_payload())), dict)
