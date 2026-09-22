"""낙찰 판정 배치 — 조회 응답을 판정 엔진 입력으로 바꾸고, 판정 결과를 전송 본문으로 만든다.

흐름 (Option A, 「AI-Backend 낙찰 판정 연동 API 기능 요구 명세서」)

    GET  /api/awarding/pending?size=N          → parse_pending
    판정                                       → offer_ranking.rank_offers
    POST /api/awarding/internal/result         ← build_result_requests

계약 출처는 Backend develop 코드다 — `AwardingPendingResponseDto` · `AwardingResultRequestDto` ·
`InternalApiKeyFilter`(헤더 `X-Internal-Api-Key`, 실패 401).

⛔ 필수 판정 필드가 빠진 board 는 판정하지 않고 계약 오류로 기록한다 — 「AI 실행 및
   Backend/Frontend 통합 인터페이스 명세」 10-1.4절. 값을 추정해 채우지 않는다.
⛔ 결과 전송은 재시도하지 않는다. 반영되지 않은 board 는 다음 조회에 다시 나온다 (명세 「공통 사항」).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from moongcheap_ai.seller_matching.offer_ranking import (
    AWARD,
    BoardDecision,
    BoardInput,
    OfferInput,
    RankingPolicy,
    rank_offers,
)

HEADER_NAME = "X-Internal-Api-Key"
PENDING_PATH = "/api/awarding/pending"
RESULT_PATH = "/api/awarding/internal/result"
PENDING_SCHEMA_VERSION = "awarding-pending.v0.1"
RESULT_SCHEMA_VERSION = "awarding-result.v0.1"
MAX_RESULTS_PER_REQUEST = 100  # 「… 명세서 응답」 1절 · Backend `@Size(max = 100)`
KST = timezone(timedelta(hours=9))


class ContractError(ValueError):
    """조회/결과 응답 계약을 믿을 수 없을 때. 결과 반영 여부는 별도 확인한다."""


@dataclass
class PendingPage:
    boards: list[tuple[BoardInput, list[OfferInput]]] = field(default_factory=list)
    skipped: list[tuple[Any, str]] = field(default_factory=list)
    has_next: bool = False
    fetched_at: str | None = None


def _int(container: Mapping[str, Any], key: str, path: str, *, nullable: bool = False) -> int | None:
    """정수 하나를 읽는다. 키가 없으면 계약 오류이며, `null` 은 nullable 필드에서만 허용한다."""
    if key not in container:
        raise ValueError(f"missing required field: {path}{key}")
    value = container[key]
    if value is None and nullable:
        return None
    # bool 은 int 의 하위형이라 먼저 막는다.
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{path}{key} must be an integer")
    return value


def _parse_board(raw: Mapping[str, Any]) -> tuple[BoardInput, list[OfferInput]]:
    """명세 10-1.5절의 조회 응답 한 board 를 판정 입력으로 바꾼다. 빠진 필드는 계약 오류다."""
    board = BoardInput(
        board_id=_int(raw, "boardId", ""),
        total_quantity=_int(raw, "totalQuantity", ""),
        participant_count=_int(raw, "participantCount", ""),
        price_max=_int(raw, "priceMax", "", nullable=True),
        max_demand_quantity_per_member=_int(raw, "maxDemandQuantityPerMember", ""),
    )
    products = raw.get("products")
    if not isinstance(products, list):
        raise TypeError("products must be a list")
    if not products:
        # Backend 는 evaluations 를 1건 이상 요구한다. 정상 흐름에서는 GB_AWARDING 전에 취소된다.
        raise ValueError("no products")

    offers = []
    for index, product in enumerate(products):
        path = f"products[{index}]."
        if not isinstance(product, Mapping):
            raise TypeError(f"products[{index}] must be an object")
        offers.append(
            OfferInput(
                product_id=_int(product, "productId", path),
                unit_price=_int(product, "price", path),
                shipping_fee=_int(product, "shippingFee", path),
                total_quantity=_int(product, "quantity", path),
                min_quantity=_int(product, "minQuantity", path),
                min_participant_count=_int(product, "minParticipantCount", path),
                # 판매자가 설정하지 않으면 null 이다 (Product-01). 키 자체가 없으면 계약 오류다.
                max_quantity_per_member=_int(product, "maxQuantityPerMember", path, nullable=True),
            )
        )
    return board, offers


def parse_pending(payload: Any) -> PendingPage:
    """조회 응답을 해석한다. 계약을 어긴 board 하나는 건너뛰고 나머지는 판정한다."""
    if not isinstance(payload, Mapping):
        raise ContractError("pending response must be a JSON object")
    if payload.get("schemaVersion") != PENDING_SCHEMA_VERSION:
        raise ContractError(f"unexpected schemaVersion: {payload.get('schemaVersion')!r}")
    boards = payload.get("boards")
    if not isinstance(boards, list):
        raise ContractError("boards must be a list")
    has_next = payload.get("hasNext")
    if not isinstance(has_next, bool):
        raise ContractError("hasNext must be a boolean")

    page = PendingPage(has_next=has_next, fetched_at=payload.get("fetchedAt"))
    for raw in boards:
        board_id = raw.get("boardId") if isinstance(raw, Mapping) else None
        try:
            if not isinstance(raw, Mapping):
                raise TypeError("board must be an object")
            board, offers = _parse_board(raw)
        except (TypeError, ValueError) as error:
            page.skipped.append((board_id, str(error)))
            continue
        page.boards.append((board, offers))
    return page


def build_result_requests(decisions: Sequence[BoardDecision], *, planned_at: datetime, judged_at: datetime) -> list[dict[str, Any]]:
    """판정 결과를 전송 본문으로 만든다. 한 요청에 board 최대 100개."""
    if planned_at.utcoffset() is None or judged_at.utcoffset() is None:
        raise ValueError("planned_at and judged_at must carry a timezone")
    # Backend: plannedAt 은 OffsetDateTime, judgedAt 은 LocalDateTime(시간대 없음). judgedAt 은 KST 벽시계로 보낸다.
    planned = planned_at.isoformat(timespec="seconds")
    judged = judged_at.astimezone(KST).replace(tzinfo=None).isoformat(timespec="seconds")
    results = [
        {
            "boardId": decision.board_id,
            "judgedAt": judged,
            "evaluations": [
                {
                    "productId": evaluation.product_id,
                    "score": float(evaluation.score),
                    "reason": evaluation.reason,
                    "isAwarded": evaluation.is_awarded,
                }
                for evaluation in decision.evaluations
            ],
        }
        for decision in decisions
        if decision.evaluations
    ]
    rule_versions = {decision.rule_version for decision in decisions}
    return [
        {
            "schemaVersion": RESULT_SCHEMA_VERSION,
            "plannedAt": planned,
            "ruleVersion": ",".join(sorted(rule_versions)),
            "results": results[start : start + MAX_RESULTS_PER_REQUEST],
        }
        for start in range(0, len(results), MAX_RESULTS_PER_REQUEST)
    ]


def _base_and_key(base_url: str, internal_key: str, timeout_seconds: float) -> tuple[str, str]:
    base = base_url.strip().rstrip("/")
    key = internal_key.strip()
    if not base:
        raise ValueError("backend base url must not be empty")
    if not key:
        raise ValueError("internal api key must not be empty")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    return base, key


def _json_or_raise(response: Any, key: str, context: str) -> dict[str, Any]:
    if not response.ok or 300 <= response.status_code < 400:
        detail = str(response.text).replace(key, "[REDACTED]")[:500]
        raise RuntimeError(f"{context} failed with HTTP {response.status_code}: {detail}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise ContractError(f"{context} response must be a JSON object")
    return payload


def fetch_pending(base_url: str, internal_key: str, *, size: int, timeout_seconds: float, http_get: Callable[..., Any]) -> dict[str, Any]:
    if isinstance(size, bool) or not isinstance(size, int) or not 1 <= size <= 100:
        raise ValueError("size must be an integer between 1 and 100")
    base, key = _base_and_key(base_url, internal_key, timeout_seconds)
    response = http_get(
        base + PENDING_PATH,
        params={"size": size},
        headers={HEADER_NAME: key, "Accept": "application/json"},
        timeout=timeout_seconds,
        allow_redirects=False,
    )
    return _json_or_raise(response, key, "awarding pending fetch")


def validate_result_response(payload: Any, *, submitted_count: int) -> dict[str, Any]:
    """200도 반영 보장은 아니다. 제출 건수와 맞는 업무 응답만 수용한다."""
    prefix = "awarding result unconfirmed: "
    if not isinstance(payload, dict) or payload.get("status") != "APPLIED":
        raise ContractError(prefix + "expected status APPLIED")
    for name in ("appliedCount", "staleRejectedCount"):
        value = payload.get(name)
        if type(value) is not int or value < 0:
            raise ContractError(prefix + name + " must be a non-negative integer")
    if payload["appliedCount"] + payload["staleRejectedCount"] != submitted_count:
        raise ContractError(prefix + "response counts do not match submitted board count")
    return payload


def summarize_reflection(requests: Sequence[Mapping[str, Any]], responses: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """Backend 가 반영한 건수. 판정 건수와 다르다.

    ⛔ `staleRejectedCount` 는 이미 처리된 board 뿐 아니라 **10개 묶음이 통째로 롤백된 경우**도 포함한다
    (Backend `DemandBoardService.applyAwardingResult` 의 `DataAccessException`/`RuntimeException` 처리).
    응답만으로는 둘을 구분할 수 없으므로 0 이 아니면 호출한 쪽이 알아채야 한다.
    """
    return {
        "submittedBoards": sum(len(request["results"]) for request in requests),
        "appliedCount": sum(response["appliedCount"] for response in responses),
        "staleRejectedCount": sum(response["staleRejectedCount"] for response in responses),
    }


def post_result(base_url: str, internal_key: str, request: Mapping[str, Any], *, timeout_seconds: float, http_post: Callable[..., Any]) -> dict[str, Any]:
    """한 번만 보낸다. 상태를 바꾸는 요청이라 재시도하지 않는다."""
    base, key = _base_and_key(base_url, internal_key, timeout_seconds)
    response = http_post(
        base + RESULT_PATH,
        json=dict(request),
        headers={HEADER_NAME: key, "Content-Type": "application/json", "Accept": "application/json"},
        timeout=timeout_seconds,
        allow_redirects=False,
    )
    try:
        payload = _json_or_raise(response, key, "awarding result post")
    except ValueError as error:
        # 잘못된 JSON/본문을 오류에 붙이지 않는다. 응답이 유실돼도 서버 반영은 가능하다.
        raise ContractError("awarding result unconfirmed: invalid JSON object") from error
    if response.status_code != 200:
        raise ContractError("awarding result unconfirmed: expected HTTP 200")
    return validate_result_response(payload, submitted_count=len(request["results"]))


def run_once(
    pending_payload: Any,
    policy: RankingPolicy,
    *,
    now: datetime,
    send: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """조회 응답 한 페이지를 판정하고, `send` 가 있으면 전송한다. 결과는 사람이 읽을 보고서다."""
    page = parse_pending(pending_payload)
    skipped = [{"boardId": board_id, "reason": reason} for board_id, reason in page.skipped]

    decisions, boards = [], []
    for board, offers in page.boards:
        try:
            decision = rank_offers(board, offers, policy)
        except ValueError as error:
            skipped.append({"boardId": board.board_id, "reason": str(error)})
            continue
        decisions.append(decision)
        boards.append(
            {
                "boardId": decision.board_id,
                "outcome": decision.outcome,
                "awardedProductId": decision.awarded_product_id if decision.outcome == AWARD else None,
                "skippedChecks": list(decision.skipped_checks),
                "evaluations": [
                    {
                        "productId": e.product_id,
                        "eligible": e.eligible,
                        "totalCost": e.total_cost,
                        "rank": e.rank,
                        "score": str(e.score),
                        "exclusionReasons": list(e.exclusion_reasons),
                        "reason": e.reason,
                    }
                    for e in decision.evaluations
                ],
            }
        )

    requests = build_result_requests(decisions, planned_at=now, judged_at=now)
    responses = [
        validate_result_response(send(request), submitted_count=len(request["results"]))
        for request in requests
    ] if send is not None else []
    return {
        "fetchedAt": page.fetched_at,
        "hasNext": page.has_next,
        "policy": {"shippingFeeUnit": policy.shipping_fee_unit, "priceCapBasis": policy.price_cap_basis},
        # 주기 실행에서 「한 건도 판정하지 못한 주기」 를 바로 알아보기 위한 요약이다.
        "counts": {
            "fetched": len(boards) + len(skipped),
            "judged": len(boards),
            "skipped": len(skipped),
            "awarded": sum(board["outcome"] == AWARD for board in boards),
        },
        "boards": boards,
        "skipped": skipped,
        "requests": requests,
        "sent": send is not None and bool(requests),
        "responses": responses,
        "reflection": summarize_reflection(requests, responses) if send is not None and requests else None,
    }
