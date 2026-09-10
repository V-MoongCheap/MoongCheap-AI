"""판매자 수요 분석 HTTP 진입 계층.

「AI 아키텍처 및 안전성 정책 초안」 11절 Serving 구조에 따라
Seller Demand Analysis 만 FastAPI 로 서비스한다. 나머지 기능은 Batch 다.

이 파일은 전송만 담당한다. 계산은 `bid_guide.py` 가 하고,
그 모듈은 표준 라이브러리만 쓰므로 FastAPI 없이도 검증된다.

Frontend 는 이 서버를 직접 호출하지 않는다. Spring Backend 만 호출한다.
"""

# ⛔ `from __future__ import annotations` 를 쓰지 않는다.
#
# 이 파일은 FastAPI 를 create_app() **안에서만** import 한다(위 docstring 참조).
# 그래서 `Request` 는 모듈 전역이 아니라 create_app() 의 지역 이름이다.
# 어노테이션을 문자열로 미루면 FastAPI 가 모듈 전역에서 `Request` 를 찾다 실패하고,
# **예외를 내지 않고** 그 파라미터를 쿼리 파라미터로 취급한다 —
# 모든 POST 가 422 `loc:["query","request"]` 로 떨어진다. `/health` 는 파라미터가
# 없어서 200 을 내므로 헬스체크로는 잡히지 않는다.
#
# 어노테이션을 즉시 평가하면 def 시점(= create_app() 안)에 `Request` 가 묶여 있어
# 지연 import 를 유지한 채로 정상 해석된다. tests/test_api_http.py 가 이 계약을 지킨다.

import hmac
import json
import logging
import os
import traceback
from pathlib import Path
from typing import Any

from .bid_guide import (
    METRICS_VERSION,
    ContractViolation,
    VersionMismatch,
    handle_bid_guide,
)

BID_GUIDE_PATH = "/internal/v1/seller/bid-guide"

# 내부 인증 — 「AI-Backend 수요 보드 생성 관련 답변」 2.2절 「서비스 간 인증 방식」.
# 시크릿은 AWS Parameter Store 에서 주입받고 받는 쪽이 헤더 값과 일치하는지 검증한다.
# ⚠️ 그 회신은 AI → Backend 방향에 대한 것이다. 본 API(Backend → AI)에도 같은 방식을
# 적용하는지는 확인 요청 중이다(명세서 8-1). 방향이 뒤집혀도 검증 위치만 바뀐다.
INTERNAL_KEY_HEADER = "X-Internal-Key"
INTERNAL_KEY_ENV = "SELLER_ANALYSIS_INTERNAL_KEY"
ALLOW_UNAUTHENTICATED_ENV = "SELLER_ANALYSIS_ALLOW_UNAUTHENTICATED"

# 계약 스키마는 저장소 규칙대로 `docs/contracts/` 에 둔다
# (`docs/PACKAGE_LAYOUT.md` · `demand_clustering` 의 plan 계약들과 같은 자리).
# ⛔ 패키지 안에 사본을 두지 않는다. 두 벌이 되면 갈라진다 — 아래 OpenAPI 는
#    Backend 에 게시한 그 파일을 그대로 읽어서 만든다.
REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACTS_DIR = REPO_ROOT / "docs" / "contracts"

# 「AI API Contract」 7절 「Error Response」 의 `INTERNAL_ERROR` 처리 —
# *"요청 추적값을 기록하고 실패 결과 반환"*. 그 「기록」이 이 logger 다.
# ⚠️ 로깅 형식·수집 경로는 아직 정해지지 않았다(명세서 8-8). 표준 logging 으로만 남긴다.
logger = logging.getLogger(__name__)


def _load_schema(name: str) -> dict:
    """게시 계약과 OpenAPI 를 한 파일에서 읽는다. 두 벌로 적으면 갈라진다.

    `$schema`·`$id` 는 문서 최상위 메타 키다. OpenAPI components 안에 그대로
    들어가면 문서 검증기가 걸고 넘어지므로 여기서만 벗긴다.
    """
    path = CONTRACTS_DIR / name
    if not path.is_file():
        # ⛔ 조용히 빈 문서를 내지 않는다. 계약 없이 뜬 서버는 Backend 가
        #    문서만 보고는 알 수 없다 — 기동 시점에 끊는다.
        raise RuntimeError(f"계약 스키마를 찾지 못했다: {path}")
    schema = json.loads(path.read_text(encoding="utf-8"))
    return {key: value for key, value in schema.items() if key not in {"$schema", "$id"}}


def _resolve_internal_key(internal_key):
    """검증에 쓸 키를 정한다. 키 없이 뜨는 것은 **명시적 선언**이어야 한다.

    ⛔ 키가 없을 때 조용히 무인증으로 열지 않는다. 그렇게 두면 인증이 빠진
    채로 배포돼도 헬스체크와 정상 응답이 모두 통과한다 — 4-1절의 422 사건과
    같은 형태의 조용한 고장이다.
    """
    if internal_key is not None:
        # ⛔ 빈 키를 그대로 받지 않는다. `expected_key = ""` 는 None 이 아니므로
        # 헬스체크가 `internal_key_required: true` 를 내는데, 실제로는 헤더 없는 요청의
        # `presented = ""` 와 `compare_digest("", "")` 가 성립해 **전부 통과한다.**
        # 「인증이 켜져 있다」고 보고하면서 아무나 들여보내는 형태라 위 4-1절 사건과 같다.
        if not internal_key.strip():
            raise RuntimeError(
                f"{INTERNAL_KEY_ENV} 로 넘어온 내부 키가 비어 있다. 빈 키는 헤더 없는 요청을 "
                f"전부 통과시킨다. 인증 없이 띄우는 것이 의도라면 internal_key=None 과 "
                f"{ALLOW_UNAUTHENTICATED_ENV}=1 을 명시한다."
            )
        return internal_key
    from_env = os.environ.get(INTERNAL_KEY_ENV, "").strip()
    if from_env:
        return from_env
    if os.environ.get(ALLOW_UNAUTHENTICATED_ENV) == "1":
        return None
    raise RuntimeError(
        f"{INTERNAL_KEY_ENV} 가 비어 있다. AWS Parameter Store 에서 주입하거나, "
        f"인증 없이 띄우는 것이 의도라면 {ALLOW_UNAUTHENTICATED_ENV}=1 을 명시한다."
    )


def create_app(internal_key=None):
    """FastAPI 앱을 만든다. FastAPI 가 없으면 앱 생성 단계에서만 실패한다.

    ⛔ **키 검증이 FastAPI import 보다 먼저다.** 순서가 뒤집히면 FastAPI 가 없는
    환경에서 `create_app()` 이 `RuntimeError` 대신 `ModuleNotFoundError` 를 낸다.
    설정이 틀린 것과 의존성이 없는 것은 다른 고장이고, 받는 쪽이 구분할 수 있어야
    한다. 저장소 기본 의존성(`requirements.txt`)에 FastAPI 가 없으므로 이것은
    가정이 아니라 **기본 환경의 실제 동작**이다.
    """
    # 설정부터 본다. 의존성이 있든 없든 같은 오류를 낸다.
    expected_key = _resolve_internal_key(internal_key)

    from fastapi import Depends, FastAPI, Request
    from fastapi.responses import JSONResponse
    from fastapi.security import APIKeyHeader

    # ⛔ `auto_error=False` 다. FastAPI 가 스스로 403 을 내면 계약이 정한 오류 바디를
    # 우회한다. 검증은 아래 라우트가 직접 하고, 이 선언은 **OpenAPI 문서용**이다.
    # 이것이 없으면 Backend 가 문서만 보고는 헤더가 필요한 줄 알 수 없다
    # (「AI API Contract」 4.4절 「내부 인증」 · 게시 명세 4.4절).
    internal_key_scheme = APIKeyHeader(name=INTERNAL_KEY_HEADER, auto_error=False)

    request_schema = _load_schema("seller_bid_guide_request_v01.schema.json")
    response_schema = _load_schema("seller_bid_guide_response_v01.schema.json")
    error_schema = _load_schema("seller_bid_guide_error_v01.schema.json")

    app = FastAPI(title="Seller Demand Analysis", version=METRICS_VERSION)

    def _error(status: int, code: str, message: str, request_id=None) -> JSONResponse:
        """「AI API Contract」 2절 「공통 규격」 의 Error Format 을 그대로 쓴다.

        그 절은 *"다음 공통 JSON 오류 형식은 **실시간 HTTP API에 적용한다**"* 라고 적고,
        본 API 가 그 실시간 HTTP API 다. 2026-09-08 까지 `{code, message}` 로 내던 것은
        2절을 열어 보지 않아서였다.

        ⚠️ `retryable` 의 코드별 값은 계약이 정하지 않았다. 2절 예시가 `INVALID_INPUT`
        에 `false` 를 쓰는 것만 확인된다. 아래 대응은 **내가 정한 것이고 확인이 필요하다** —
        요청을 고쳐야 풀리는 오류는 `false`, 그대로 다시 보내 볼 만한 오류는 `true`.
        """
        return JSONResponse(
            status_code=status,
            content={
                "request_id": request_id,
                "error": {
                    "code": code,
                    "message": message,
                    "retryable": code == "INTERNAL_ERROR",
                    # 계약 예시가 빈 객체다. 무엇을 담을지 정해지지 않았다.
                    "details": {},
                },
            },
        )

    @app.get("/health")
    def health() -> dict[str, Any]:
        # 인증 적용 여부를 헬스체크에 드러낸다. 무인증으로 뜬 것이 눈에 보여야 한다.
        return {
            "status": "ok",
            "metrics_version": METRICS_VERSION,
            "internal_key_required": expected_key is not None,
        }

    @app.post(
        BID_GUIDE_PATH,
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {"application/json": {"schema": request_schema}},
            }
        },
        responses={
            200: {
                "description": "수요 지표 산출 결과",
                "content": {"application/json": {"schema": response_schema}},
            },
            400: {
                "description": "계약 위반(INVALID_INPUT) · 지원하지 않는 버전(VERSION_MISMATCH)",
                "content": {"application/json": {"schema": error_schema}},
            },
            403: {
                "description": f"{INTERNAL_KEY_HEADER} 누락·불일치 (2026-09-09 Backend 확정)",
                "content": {"application/json": {"schema": error_schema}},
            },
            500: {
                "description": "분류되지 않은 AI 내부 오류(INTERNAL_ERROR)",
                "content": {"application/json": {"schema": error_schema}},
            },
        },
    )
    async def bid_guide(
        request: Request, _presented_key: str = Depends(internal_key_scheme)
    ) -> Any:
        if expected_key is not None:
            presented = request.headers.get(INTERNAL_KEY_HEADER, "")
            # 상수 시간 비교. 일치 여부를 길이·조기 반환으로 흘리지 않는다.
            if not hmac.compare_digest(presented, expected_key):
                # 2026-09-09 Backend 회신으로 확정 — **403 · `UNAUTHORIZED`**.
                # *"401은 WWW-Authenticate 헤더로 인증 방식을 안내하는 게 규약인데
                #   내부 키 인증에는 해당이 없어, 키 누락과 불일치를 구분하지 않고
                #   403 하나로 통일하는 게 낫다고 봅니다."*
                # 「AI API Contract」 2절 「공통 규격」 이 오류 코드와 HTTP 상태를
                # Backend 예외 체계와 **공동 확정**한다고 정하고 있어 그대로 따랐다.
                # ⛔ 누락과 불일치를 구분하지 않는다. 구분하면 키 존재 여부가 새어 나간다.
                # 본문을 읽기 전에 끊으므로 request_id 는 없다.
                return _error(403, "UNAUTHORIZED", f"{INTERNAL_KEY_HEADER} is missing or invalid")
        try:
            payload = await request.json()
        except Exception:
            # 형식 오류다. 명세서 5.6절 「오류 응답」 의 첫 행에 해당한다.
            return _error(400, "INVALID_INPUT", "request body must be JSON")

        # 오류 바디의 `request_id` 는 요청에서 되돌려 준다. 계약 위반 요청에서도
        # 추적값은 살려야 Backend 가 어느 호출이 실패했는지 잇는다.
        # ⛔ 값을 검증하기 전이므로 문자열일 때만 쓴다. 그 외에는 null 로 둔다.
        traced = payload.get("request_id") if isinstance(payload, dict) else None
        if not isinstance(traced, str):
            traced = None

        try:
            return handle_bid_guide(payload)
        except VersionMismatch as exc:
            return _error(400, "VERSION_MISMATCH", str(exc), traced)
        except ContractViolation as exc:
            # 계약 위반은 400 이다. 추정해서 계산하지 않는다.
            return _error(400, "INVALID_INPUT", str(exc), traced)
        except Exception as exc:
            # 「AI API Contract」 7절 — *"요청 추적값을 기록하고 실패 결과 반환"*.
            # ⛔ 본문을 로그에 남기지 않는다. 개인 단위 필드가 섞여 들어온 요청이
            # 그대로 로그로 새어 나가면 20절 「개인정보 안전성 평가」 를 깬다.
            # 추적값과 예외 종류만 남기고, 스택은 logging 이 따로 붙인다.
            # ⛔ `logger.exception` 을 쓰지 않는다. 그것은 트레이스백의 마지막 줄로
            # `ExcType: str(exc)` 를 붙이는데, 예외 메시지에는 그 예외를 일으킨 **입력값이
            # 그대로 실릴 수 있다.** 포맷 문자열에 본문을 안 넣는 것만으로는 부족하다.
            # 프레임(파일·행·호출)만 남기고 메시지는 버린다 — 어디서 터졌는지는 남고
            # 무엇이 들어왔는지는 남지 않는다.
            logger.error(
                "bid-guide internal error: request_id=%s error=%s at %s",
                traced,
                type(exc).__name__,
                " | ".join(
                    f"{frame.filename}:{frame.lineno} {frame.name}"
                    for frame in traceback.extract_tb(exc.__traceback__)
                ),
            )
            return _error(500, "INTERNAL_ERROR", type(exc).__name__, traced)

    return app
