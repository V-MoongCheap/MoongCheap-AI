"""낙찰 판정 배치 — 조회 응답 → 판정 → 결과 전송 본문.

기준
- Backend develop `AwardingPendingResponseDto` · `AwardingResultRequestDto` · `InternalApiKeyFilter`
- 「AI-Backend 낙찰 판정 연동 API 기능 요구 명세서」 · 「… 응답」 1절 (`size` 1~100, `results` 최대 100)
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from moongcheap_ai.seller_matching.awarding_batch import (
    HEADER_NAME,
    RESULT_SCHEMA_VERSION,
    ContractError,
    build_result_requests,
    fetch_pending,
    parse_pending,
    post_result,
    run_once,
)
from moongcheap_ai.seller_matching.offer_ranking import RankingPolicy

KST = timezone(timedelta(hours=9))
POLICY = RankingPolicy(shipping_fee_unit="PER_BOARD", price_cap_basis="UNIT_PRICE")
NOW = datetime(2026, 9, 17, 14, 5, 0, tzinfo=KST)


def _product(**overrides):
    values = {
        "productId": 5001,
        "sellerId": 7001,
        "price": 15000,
        "quantity": 40,
        "shippingFee": 3000,
        "minQuantity": 10,
        "minParticipantCount": 3,
        "maxQuantityPerMember": None,
    }
    values.update(overrides)
    return values


def _board(**overrides):
    values = {
        "boardId": 1001,
        "catalogId": 2002,
        "priceMin": 10000,
        "priceMax": 20000,
        "saleEndAt": "2026-09-15T12:00:00",
        "calculationStartedAt": "2026-09-15T12:05:00",
        "participantCount": 12,
        "totalQuantity": 34,
        "maxDemandQuantityPerMember": 4,
        "products": [_product()],
    }
    values.update(overrides)
    return values


def _page(*boards, has_next=False):
    return {
        "schemaVersion": "awarding-pending.v0.1",
        "fetchedAt": "2026-09-17T14:05:00",
        "boards": list(boards),
        "size": len(boards),
        "hasNext": has_next,
    }


# ── 조회 응답 해석 ────────────────────────────────────────


def test_pending_board_maps_to_engine_input():
    page = parse_pending(_page(_board(products=[_product(maxQuantityPerMember=5)])))

    board, offers = page.boards[0]
    assert (board.board_id, board.total_quantity, board.participant_count, board.price_max) == (1001, 34, 12, 20000)
    assert board.max_demand_quantity_per_member == 4
    assert (offers[0].product_id, offers[0].unit_price, offers[0].shipping_fee, offers[0].total_quantity) == (5001, 15000, 3000, 40)
    assert (offers[0].min_quantity, offers[0].min_participant_count, offers[0].max_quantity_per_member) == (10, 3, 5)


@pytest.mark.parametrize(
    "missing, reason",
    [
        ("shippingFee", "missing required field: products[0].shippingFee"),
        ("minQuantity", "missing required field: products[0].minQuantity"),
        ("minParticipantCount", "missing required field: products[0].minParticipantCount"),
        ("maxQuantityPerMember", "missing required field: products[0].maxQuantityPerMember"),
    ],
)
def test_missing_product_condition_is_a_contract_error(missing, reason):
    """명세 10-1.4절 — 필수 판정 필드가 빠지면 판정하지 않고 계약 오류로 기록한다."""
    product = {k: v for k, v in _product().items() if k != missing}

    page = parse_pending(_page(_board(products=[product])))

    assert page.boards == []
    assert page.skipped == [(1001, reason)]


def test_missing_board_aggregate_is_a_contract_error():
    board = {k: v for k, v in _board().items() if k != "maxDemandQuantityPerMember"}

    page = parse_pending(_page(board))

    assert page.skipped == [(1001, "missing required field: maxDemandQuantityPerMember")]


def test_null_is_allowed_only_where_the_contract_allows_it():
    ok = parse_pending(_page(_board(priceMax=None, products=[_product(maxQuantityPerMember=None)])))
    bad = parse_pending(_page(_board(totalQuantity=None)))

    assert ok.boards[0][0].price_max is None
    assert ok.boards[0][1][0].max_quantity_per_member is None
    assert bad.skipped == [(1001, "totalQuantity must be an integer")]


def test_board_without_products_is_skipped_because_backend_requires_evaluations():
    page = parse_pending(_page(_board(products=[])))

    assert page.boards == []
    assert page.skipped == [(1001, "no products")]


def test_bad_board_is_skipped_without_dropping_other_boards():
    good = _board(boardId=1, products=[_product(productId=1)])
    bad = _board(boardId=2, products=[_product(productId=2, price=None)])

    page = parse_pending(_page(good, bad))

    assert [board.board_id for board, _ in page.boards] == [1]
    assert page.skipped == [(2, "products[0].price must be an integer")]


def test_unexpected_schema_version_rejects_whole_page():
    payload = _page(_board())
    payload["schemaVersion"] = "awarding-pending.v9"

    with pytest.raises(ContractError, match="schemaVersion"):
        parse_pending(payload)


def test_boolean_is_not_accepted_as_integer():
    page = parse_pending(_page(_board(totalQuantity=True)))

    assert page.skipped == [(1001, "totalQuantity must be an integer")]


def test_has_next_is_carried():
    assert parse_pending(_page(has_next=True)).has_next is True


# ── 결과 전송 본문 ────────────────────────────────────────


def _decisions(*boards):
    from moongcheap_ai.seller_matching.offer_ranking import rank_offers

    page = parse_pending(_page(*boards))
    return [rank_offers(board, offers, POLICY) for board, offers in page.boards]


def test_result_request_matches_backend_dto():
    decisions = _decisions(_board(products=[_product(productId=5001), _product(productId=5002, price=21000)]))

    (request,) = build_result_requests(decisions, planned_at=NOW, judged_at=NOW)

    assert request["schemaVersion"] == RESULT_SCHEMA_VERSION
    assert request["plannedAt"] == "2026-09-17T14:05:00+09:00"
    assert request["ruleVersion"] == "offer-ranking-v0.2"
    (result,) = request["results"]
    assert result["boardId"] == 1001
    assert result["judgedAt"] == "2026-09-17T14:05:00"  # Backend 는 시간대 없는 LocalDateTime 으로 받는다
    assert [e["productId"] for e in result["evaluations"]] == [5001, 5002]
    assert [e["isAwarded"] for e in result["evaluations"]] == [True, False]
    assert [e["score"] for e in result["evaluations"]] == [1.0, 0.0]
    assert all(isinstance(e["reason"], str) and len(e["reason"]) <= 500 for e in result["evaluations"])
    json.dumps(request)  # 직렬화 가능


def test_results_are_split_into_requests_of_at_most_100_boards():
    boards = [_board(boardId=i, products=[_product(productId=i)]) for i in range(1, 206)]

    requests = build_result_requests(_decisions(*boards), planned_at=NOW, judged_at=NOW)

    assert [len(r["results"]) for r in requests] == [100, 100, 5]


def test_no_decisions_produce_no_requests():
    assert build_result_requests([], planned_at=NOW, judged_at=NOW) == []


def test_naive_times_are_rejected():
    with pytest.raises(ValueError, match="timezone"):
        build_result_requests([], planned_at=datetime(2026, 9, 17), judged_at=NOW)  # noqa: DTZ001 — 시간대 없는 값을 거절하는지 본다


# ── HTTP ─────────────────────────────────────────────────


class _Response:
    def __init__(self, status, payload=None, text=""):
        self.status_code = status
        self.ok = 200 <= status < 300
        self._payload = payload
        self.text = text or json.dumps(payload)

    def json(self):
        return self._payload


def test_fetch_sends_internal_api_key_and_size():
    calls = []

    def http_get(url, **kwargs):
        calls.append((url, kwargs))
        return _Response(200, _page())

    fetch_pending("http://backend/", "secret", size=50, timeout_seconds=5, http_get=http_get)

    url, kwargs = calls[0]
    assert url == "http://backend/api/awarding/pending"
    assert kwargs["params"] == {"size": 50}
    assert kwargs["headers"][HEADER_NAME] == "secret"
    assert HEADER_NAME == "X-Internal-Api-Key"


@pytest.mark.parametrize("size", [0, 101])
def test_fetch_rejects_size_outside_contract(size):
    with pytest.raises(ValueError, match="size"):
        fetch_pending("http://backend", "secret", size=size, timeout_seconds=5, http_get=lambda *a, **k: None)


def test_http_error_hides_key():
    def http_get(url, **kwargs):
        return _Response(401, text='{"error":"bad key secret"}')

    with pytest.raises(RuntimeError) as error:
        fetch_pending("http://backend", "secret", size=50, timeout_seconds=5, http_get=http_get)

    assert "401" in str(error.value)
    assert "secret" not in str(error.value)


def test_post_is_sent_once_even_on_failure():
    calls = []

    def http_post(url, **kwargs):
        calls.append(url)
        return _Response(500, text="boom")

    with pytest.raises(RuntimeError):
        post_result("http://backend", "secret", {"results": []}, timeout_seconds=5, http_post=http_post)

    assert calls == ["http://backend/api/awarding/internal/result"]


# ── 한 번 실행 ────────────────────────────────────────────


def test_dry_run_decides_without_posting():
    report = run_once(_page(_board()), POLICY, now=NOW, send=None)

    assert report["sent"] is False
    assert report["responses"] == []
    assert report["boards"][0]["outcome"] == "AWARD"
    assert report["boards"][0]["awardedProductId"] == 5001
    assert report["requests"][0]["results"][0]["boardId"] == 1001


def test_send_posts_each_request_and_keeps_backend_counts():
    sent = []

    def send(request):
        sent.append(request)
        return {"status": "APPLIED", "appliedCount": len(request["results"]), "staleRejectedCount": 0}

    report = run_once(_page(_board()), POLICY, now=NOW, send=send)

    assert len(sent) == 1
    assert report["sent"] is True
    assert report["responses"] == [{"status": "APPLIED", "appliedCount": 1, "staleRejectedCount": 0}]


def test_report_lists_skipped_boards():
    report = run_once(_page(_board(boardId=1), _board(boardId=2, products=[])), POLICY, now=NOW, send=None)

    assert [b["boardId"] for b in report["boards"]] == [1]
    assert report["skipped"] == [{"boardId": 2, "reason": "no products"}]
