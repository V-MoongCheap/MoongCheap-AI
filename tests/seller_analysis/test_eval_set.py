"""영역 2 고정 평가셋의 규격 회귀.

「AI 평가 데이터셋 및 평가 지표 정의서」 17절 구성표·파일 분리·생성 결정성을 본다.

⛔ 정답은 생성기가 16절 산식으로 따로 세운 값이다. 구현이 만든 값이 아니다.
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


class EvalSetShapeTest(unittest.TestCase):
    def setUp(self):
        self.eval_rows = read_csv("seller_analysis_eval_v1.csv")
        self.truth_rows = read_csv("seller_analysis_ground_truth_v1.csv")

    def test_dataset_has_the_documented_size(self):
        self.assertEqual(len(self.eval_rows), 100)
        self.assertEqual(len(self.truth_rows), 100)

    def test_scenario_counts_match_the_documented_table(self):
        counted: dict[str, int] = {}
        for row in self.truth_rows:
            counted[row["primary_scenario"]] = counted.get(row["primary_scenario"], 0) + 1
        self.assertEqual(counted, SCENARIO_QUOTA)

    def test_input_file_carries_no_answers(self):
        """⛔ 정답이 입력 파일에 섞이면 평가가 성립하지 않는다 (2절)."""
        self.assertEqual(list(self.eval_rows[0]), EVAL_FIELDS)
        self.assertEqual(list(self.truth_rows[0]), GROUND_TRUTH_FIELDS)
        for column in self.eval_rows[0]:
            self.assertFalse(column.startswith("expected_"), column)

    def test_ids_line_up_between_the_two_files(self):
        self.assertEqual(
            [row["eval_id"] for row in self.eval_rows],
            [row["eval_id"] for row in self.truth_rows],
        )
        self.assertEqual(len({row["eval_id"] for row in self.eval_rows}), 100)

    def test_generation_is_deterministic(self):
        """난수를 쓰지 않으므로 다시 만들어도 파일과 같아야 한다."""
        regenerated = build_cases()
        self.assertEqual(len(regenerated), 100)
        for case, row in zip(regenerated, self.truth_rows):
            self.assertEqual(case["eval_id"], row["eval_id"])
            self.assertEqual("|".join(case["scenario_tags"]), row["scenario_tags"])
            self.assertEqual(str(case["expected_moq_status"]), row["expected_moq_status"])

    def test_every_case_keeps_the_minimum_participant_rule(self):
        for row in self.eval_rows:
            with self.subTest(eval_id=row["eval_id"]):
                self.assertGreaterEqual(int(row["participant_count"]), MIN_PARTICIPANTS)
                self.assertLessEqual(
                    int(row["participant_count"]), int(row["total_demand_quantity"])
                )

    def test_all_five_invalid_input_kinds_from_the_document_are_present(self):
        kinds = {
            tag
            for row in self.truth_rows
            for tag in row["scenario_tags"].split("|")
            if row["expected_request_result"] == "REJECTED"
        }
        for kind in (
            "NON_POSITIVE_QUANTITY",
            "WRONG_DATA_TYPE",
            "MISSING_REQUIRED_FIELD",
            "UNDECLARED_EXTRA_FIELD",
            "PII_FIELD",
        ):
            self.assertIn(kind, kinds)

    def test_rejected_cases_carry_no_expected_numbers(self):
        """거절이 정답인 행에 수치를 적으면 Numeric Accuracy 분모가 오염된다 (18.1절)."""
        for row in self.truth_rows:
            if row["expected_request_result"] == "REJECTED":
                self.assertEqual(row["expected_moq_attainment_ratio"], "")
                self.assertEqual(row["expected_supply_status"], "")

    def test_ground_truth_never_depends_on_a_rounding_policy(self):
        """정상 Case 의 비율은 소수 4자리에서 정확히 떨어져야 한다."""
        for row in self.eval_rows:
            if row["invalid_input_overrides"]:
                continue
            with self.subTest(eval_id=row["eval_id"]):
                demand = int(row["total_demand_quantity"])
                _exact_ratio(demand, int(row["minimum_success_quantity"]))
                _exact_ratio(int(row["maximum_supply_quantity"]), demand)

    def test_generator_refuses_a_ratio_that_needs_rounding(self):
        with self.assertRaises(GeneratorError):
            _exact_ratio(1, 3)

    def test_generator_does_not_call_the_implementation(self):
        """⛔ 구현으로 정답을 만들면 구현이 틀려도 100% 가 나온다."""
        source = (
            REPO_ROOT / "src" / "moongcheap_ai" / "seller_analysis" / "evaluation" / "eval_set.py"
        ).read_text(encoding="utf-8")
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith(("import ", "from ")):
                self.assertNotIn("bid_guide", stripped, stripped)


