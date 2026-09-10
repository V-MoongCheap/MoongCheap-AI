"""HTTP 계약 통합 검사.

`create_app()` 이 import 되는 것과 앱이 실제로 뜨는 것은 다른 사실이다.
FastAPI 가 설치되지 않은 환경에서는 건너뛰되, **건너뛴다는 사실이 보이게** 한다.
설치 방법은 `requirements-api.txt` 에 있다.
"""

from __future__ import annotations

import os
import unittest
from unittest import mock

from moongcheap_ai.seller_analysis.api import (
    ALLOW_UNAUTHENTICATED_ENV,
    _resolve_internal_key,
    BID_GUIDE_PATH,
    INTERNAL_KEY_ENV,
    INTERNAL_KEY_HEADER,
    create_app,
)
from moongcheap_ai.seller_analysis.bid_guide import METRICS_VERSION

try:  # pragma: no cover - 환경에 따라 갈린다
    from fastapi.testclient import TestClient

    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    TestClient = None
    FASTAPI_AVAILABLE = False

TEST_KEY = "test-internal-key"


def valid_payload(**overrides):
    payload = {
        "request_id": "http-001",
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


@unittest.skipUnless(
    FASTAPI_AVAILABLE,
    "fastapi 미설치 — requirements-api.txt 로 설치해야 HTTP 계약이 검증된다",
)
class BidGuideHttpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(create_app(internal_key=TEST_KEY))
        cls.auth = {INTERNAL_KEY_HEADER: TEST_KEY}

    def post(self, payload, **kwargs):
        headers = dict(self.auth)
        headers.update(kwargs.pop("headers", {}))
        return self.client.post(BID_GUIDE_PATH, json=payload, headers=headers, **kwargs)

    def test_health_reports_metrics_version_and_auth_mode(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["metrics_version"], METRICS_VERSION)
        # 무인증으로 떠 있는 것이 헬스체크에서 보여야 한다.
        self.assertTrue(body["internal_key_required"])

    def test_valid_request_returns_computed_guide(self):
        response = self.post(valid_payload())
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertGreaterEqual(body["metrics"]["moq_attainment_ratio"], 1.0)
        self.assertEqual(body["calculation_policy_version"], METRICS_VERSION)
        self.assertEqual(body["unresolved_items"], [])

    def test_forbidden_field_is_rejected_with_invalid_input(self):
        response = self.post(valid_payload(member_ids=["u1", "u2"]))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "INVALID_INPUT")

    def test_error_body_follows_the_contract_error_format(self):
        """「AI API Contract」 2절 「공통 규격」 의 Error Format — 실시간 HTTP API 에 적용된다."""
        body = self.post(valid_payload(total_demand_quantity=0)).json()
        self.assertEqual(set(body), {"request_id", "error"})
        self.assertEqual(
            set(body["error"]), {"code", "message", "retryable", "details"}
        )
        self.assertIsInstance(body["error"]["retryable"], bool)
        self.assertEqual(body["error"]["details"], {})

    def test_error_body_echoes_the_request_id(self):
        """계약 위반 요청에서도 추적값은 살려야 Backend 가 어느 호출인지 잇는다."""
        body = self.post(valid_payload(total_demand_quantity=0)).json()
        self.assertEqual(body["request_id"], "http-001")

    def test_request_id_is_null_when_it_cannot_be_trusted(self):
        """검증 전 값이므로 문자열이 아니면 되돌려 주지 않는다."""
        body = self.post(valid_payload(request_id=12345)).json()
        self.assertIsNone(body["request_id"])

    def test_input_errors_are_not_marked_retryable(self):
        """요청을 고쳐야 풀리는 오류를 재시도 가능으로 내보내면 Backend 가 헛돈다."""
        for payload in (
            valid_payload(total_demand_quantity=0),
            valid_payload(calculation_policy_version="seller-metrics-v999"),
        ):
            with self.subTest(payload=payload):
                self.assertFalse(self.post(payload).json()["error"]["retryable"])

    def test_malformed_json_is_rejected_with_invalid_input(self):
        response = self.client.post(
            BID_GUIDE_PATH,
            content=b"{not json",
            headers={**self.auth, "content-type": "application/json"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "INVALID_INPUT")

    def test_unsupported_policy_version_is_rejected_with_version_mismatch(self):
        response = self.post(valid_payload(calculation_policy_version="seller-metrics-v999"))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "VERSION_MISMATCH")

    def test_contract_violation_does_not_get_reported_as_version_mismatch(self):
        """두 코드가 섞이면 Backend 가 재시도 여부를 잘못 고른다."""
        response = self.post(valid_payload(total_demand_quantity=0))
        self.assertEqual(response.json()["error"]["code"], "INVALID_INPUT")

    def test_missing_internal_key_is_rejected(self):
        response = self.client.post(BID_GUIDE_PATH, json=valid_payload())
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "UNAUTHORIZED")
        # 본문을 읽기 전에 끊으므로 추적값이 없다.
        self.assertIsNone(response.json()["request_id"])

    def test_wrong_internal_key_is_rejected(self):
        response = self.client.post(
            BID_GUIDE_PATH,
            json=valid_payload(),
            headers={INTERNAL_KEY_HEADER: "wrong-key"},
        )
        self.assertEqual(response.status_code, 403)

    def test_auth_is_checked_before_the_body_is_parsed(self):
        """키가 틀리면 본문 내용이 무엇이든 403 이다. 오류 메시지로 계약을 흘리지 않는다."""
        response = self.client.post(
            BID_GUIDE_PATH,
            content=b"{not json",
            headers={"content-type": "application/json"},
        )
        self.assertEqual(response.status_code, 403)

    def test_unclassified_failure_becomes_internal_error_not_a_stack_trace(self):
        """분류되지 않은 오류도 계약된 코드로 나가되 내부 사정은 흘리지 않는다."""
        with mock.patch(
            "moongcheap_ai.seller_analysis.api.handle_bid_guide",
            side_effect=RuntimeError("secret internal detail"),
        ):
            response = self.post(valid_payload())
        self.assertEqual(response.status_code, 500)
        body = response.json()
        self.assertEqual(body["error"]["code"], "INTERNAL_ERROR")
        self.assertNotIn("secret internal detail", body["error"]["message"])
        # 분류되지 않은 내부 오류는 그대로 다시 보내 볼 만하다.
        self.assertTrue(body["error"]["retryable"])

    def test_openapi_document_exposes_the_contract_path(self):
        schema = self.client.get("/openapi.json").json()
        self.assertIn(BID_GUIDE_PATH, schema["paths"])

    def test_openapi_declares_the_request_body(self):
        """⛔ requestBody 가 없으면 Backend 가 무엇을 보내야 하는지 문서로 알 수 없다."""
        operation = self.client.get("/openapi.json").json()["paths"][BID_GUIDE_PATH]["post"]
        body_schema = operation["requestBody"]["content"]["application/json"]["schema"]
        self.assertTrue(operation["requestBody"]["required"])
        self.assertIn("calculation_policy_version", body_schema["required"])
        self.assertFalse(body_schema["additionalProperties"])

    def test_openapi_declares_the_internal_key_header(self):
        """⛔ 선언이 없으면 Backend 가 문서만 보고는 헤더가 필요한 줄 모른다."""
        doc = self.client.get("/openapi.json").json()
        schemes = doc["components"]["securitySchemes"]
        declared = [v for v in schemes.values() if v.get("name") == INTERNAL_KEY_HEADER]
        self.assertTrue(declared, schemes)
        self.assertEqual(declared[0]["type"], "apiKey")
        self.assertEqual(declared[0]["in"], "header")
        self.assertTrue(doc["paths"][BID_GUIDE_PATH]["post"].get("security"))

    def test_declaring_the_header_does_not_hijack_the_error_body(self):
        """FastAPI 가 스스로 403 을 내면 계약이 정한 오류 바디를 우회한다."""
        response = self.client.post(BID_GUIDE_PATH, json=valid_payload())
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "UNAUTHORIZED")

    def test_internal_error_records_the_request_id(self):
        """「AI API Contract」 7절 — *"요청 추적값을 기록하고 실패 결과 반환"*."""
        with mock.patch(
            "moongcheap_ai.seller_analysis.api.handle_bid_guide",
            side_effect=RuntimeError("boom"),
        ):
            with self.assertLogs("moongcheap_ai.seller_analysis.api", level="ERROR") as logs:
                response = self.post(valid_payload())
        self.assertEqual(response.status_code, 500)
        recorded = "\n".join(logs.output)
        self.assertIn("http-001", recorded)
        self.assertIn("RuntimeError", recorded)

    def test_internal_error_log_does_not_carry_the_request_body(self):
        """⛔ 개인 단위 필드가 섞인 요청이 로그로 새어 나가면 안 된다."""
        with mock.patch(
            "moongcheap_ai.seller_analysis.api.handle_bid_guide",
            side_effect=RuntimeError("boom"),
        ):
            with self.assertLogs("moongcheap_ai.seller_analysis.api", level="ERROR") as logs:
                self.client.post(
                    BID_GUIDE_PATH,
                    json={**valid_payload(), "cluster_ref": "SECRET_CLUSTER_SENTINEL"},
                    headers=self.auth,
                )
        recorded = "\n".join(logs.output)
        self.assertNotIn("SECRET_CLUSTER_SENTINEL", recorded)

    def test_openapi_declares_success_and_error_responses(self):
        operation = self.client.get("/openapi.json").json()["paths"][BID_GUIDE_PATH]["post"]
        for status in ("200", "400", "403", "500"):
            self.assertIn(status, operation["responses"], status)
        success = operation["responses"]["200"]["content"]["application/json"]["schema"]
        self.assertIn("metrics", success["required"])
        error = operation["responses"]["400"]["content"]["application/json"]["schema"]
        self.assertIn(
            "VERSION_MISMATCH",
            error["properties"]["error"]["properties"]["code"]["enum"],
        )


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi 미설치")
class InternalKeyConfigurationTest(unittest.TestCase):
    """키 설정이 없을 때 **조용히 열리지 않는지** 본다."""

    def test_app_refuses_to_start_without_a_key(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                create_app()

    def test_key_is_read_from_the_environment(self):
        with mock.patch.dict(os.environ, {INTERNAL_KEY_ENV: "env-key"}, clear=True):
            client = TestClient(create_app())
        response = client.post(
            BID_GUIDE_PATH, json=valid_payload(), headers={INTERNAL_KEY_HEADER: "env-key"}
        )
        self.assertEqual(response.status_code, 200)

    def test_unauthenticated_mode_must_be_declared_explicitly(self):
        with mock.patch.dict(os.environ, {ALLOW_UNAUTHENTICATED_ENV: "1"}, clear=True):
            client = TestClient(create_app())
        self.assertFalse(client.get("/health").json()["internal_key_required"])
        self.assertEqual(client.post(BID_GUIDE_PATH, json=valid_payload()).status_code, 200)


class KeyCheckOrderTest(unittest.TestCase):
    """⛔ 키 검증은 FastAPI import 보다 **먼저** 와야 한다.

    저장소 기본 의존성(`requirements.txt`)에 FastAPI 가 없다. 순서가 뒤집히면
    기본 환경에서 `create_app()` 이 `RuntimeError` 가 아니라 `ModuleNotFoundError`
    를 내고, 아래 `EmptyInternalKeyTest` 두 건이 그대로 깨진다.

    이 검사는 **FastAPI 설치 여부와 무관하게** 돌아야 하므로 소스 순서를 본다.
    실제로 FastAPI 를 지우고 돌려 재현했던 결함이다(2026-09-10 리뷰 지적).
    """

    def test_key_is_resolved_before_fastapi_is_imported(self):
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[2]
            / "src" / "moongcheap_ai" / "seller_analysis" / "api.py"
        ).read_text(encoding="utf-8")
        body = source.split("def create_app", 1)[1]
        resolve_at = body.index("_resolve_internal_key(internal_key)")
        import_at = body.index("from fastapi import")
        self.assertLess(
            resolve_at,
            import_at,
            "키 검증이 FastAPI import 뒤에 있다. 기본 환경에서 오류 종류가 바뀐다",
        )


class EmptyInternalKeyTest(unittest.TestCase):
    """B1 — 빈 키는 「인증 켜짐」이라 보고하면서 아무나 통과시켰다.

    `expected_key = ""` 는 None 이 아니므로 `/health` 가 `internal_key_required: true`
    를 낸다. 그런데 헤더 없는 요청의 `presented` 도 `""` 라서 `compare_digest` 가
    성립한다 — 켜졌다고 말하면서 열려 있는, 가장 나쁜 형태의 조용한 고장이다.
    """

    def test_explicit_empty_key_is_refused_at_startup(self):
        for value in ("", "   "):
            with self.subTest(value=value):
                with self.assertRaises(RuntimeError) as caught:
                    create_app(internal_key=value)
                self.assertIn("비어 있다", str(caught.exception))

    def test_unauthenticated_start_stays_explicit(self):
        """무인증으로 띄우는 길은 막지 않는다. **명시**를 요구할 뿐이다.

        ⛔ 여기서 `create_app()` 을 부르지 않는다. 그러면 FastAPI 가 필요해져서
        저장소 기본 환경에서 이 검사가 의존성 문제로 깨진다. 확인하려는 것은
        **키 해석 규칙**이므로 그 함수를 직접 본다. 앱이 실제로 뜨는지는 아래
        `UnauthenticatedAppTest` 가 FastAPI 가 있을 때만 본다.
        """
        env = {ALLOW_UNAUTHENTICATED_ENV: "1", INTERNAL_KEY_ENV: ""}
        with mock.patch.dict(os.environ, env, clear=False):
            self.assertIsNone(_resolve_internal_key(None))

    def test_missing_key_without_the_explicit_flag_is_refused(self):
        """명시가 없으면 거절한다. 조용히 무인증으로 열리지 않는다."""
        env = {INTERNAL_KEY_ENV: ""}
        with mock.patch.dict(os.environ, env, clear=False):
            os.environ.pop(ALLOW_UNAUTHENTICATED_ENV, None)
            with self.assertRaises(RuntimeError):
                _resolve_internal_key(None)


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi 미설치")
class UnauthenticatedAppTest(unittest.TestCase):
    """무인증 선언이 실제로 앱을 띄우는지. 앱 생성이라 FastAPI 가 필요하다."""

    def test_app_starts_when_unauthenticated_is_declared(self):
        env = {ALLOW_UNAUTHENTICATED_ENV: "1", INTERNAL_KEY_ENV: ""}
        with mock.patch.dict(os.environ, env, clear=False):
            app = create_app()
        self.assertIsNotNone(app)


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi 미설치")
class InternalErrorLogTest(unittest.TestCase):
    """B2 — 예외 메시지가 로그에 그대로 남았다.

    포맷 문자열에 본문을 안 넣는 것으로는 부족하다. `logger.exception` 이 붙이는
    트레이스백의 마지막 줄이 `ExcType: str(exc)` 이고, 그 메시지에는 예외를 일으킨
    **입력값이 실릴 수 있다.** 20절 「개인정보 안전성 평가」 가 걸리는 자리다.
    """

    def test_exception_message_never_reaches_the_log(self):
        import io
        import logging

        from moongcheap_ai.seller_analysis import api

        sentinel = "SYNTHETIC_PRIVATE_VALUE_NOT_REAL"
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter("%(message)s"))
        previous = api.logger.propagate
        api.logger.propagate = False
        api.logger.addHandler(handler)
        try:
            with TestClient(create_app(internal_key=TEST_KEY)) as client:
                with mock.patch.object(
                    api, "handle_bid_guide", side_effect=RuntimeError(sentinel)
                ):
                    response = client.post(
                        BID_GUIDE_PATH,
                        json=valid_payload(),
                        headers={INTERNAL_KEY_HEADER: TEST_KEY},
                    )
        finally:
            api.logger.removeHandler(handler)
            api.logger.propagate = previous

        rendered = stream.getvalue()
        self.assertEqual(response.status_code, 500)
        self.assertNotIn(sentinel, response.text)
        self.assertNotIn(sentinel, rendered)
        # 추적은 살아 있어야 한다 — 무엇이 들어왔는지가 아니라 어디서 터졌는지.
        self.assertIn("RuntimeError", rendered)
        self.assertIn("http-001", rendered)
        self.assertIn("api.py", rendered)


class TransportLayerBoundaryTest(unittest.TestCase):
    """⛔ 전송 계층만 FastAPI 를 안다. 계산 계층은 몰라야 한다."""

    def test_fastapi_is_imported_only_inside_create_app(self):
        from pathlib import Path

        api_source = (
            Path(__file__).resolve().parents[2]
            / "src" / "moongcheap_ai" / "seller_analysis" / "api.py"
        ).read_text(encoding="utf-8")
        self.assertIn("from fastapi import", api_source)
        # 모듈을 불러오는 것만으로 FastAPI 를 요구하지 않는다. create_app 안에서만 import 한다.
        self.assertNotIn("\nfrom fastapi", "\n" + api_source.split("def create_app")[0])
