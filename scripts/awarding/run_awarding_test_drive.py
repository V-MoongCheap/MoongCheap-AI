"""낙찰 판정 시험 운전 — 조회 → 판정 → (선택) 전송을 한 번 실행하고 보고서를 남긴다.

세 가지 방식

1) 파일로만 판정 (네트워크 없음, 전송 없음)
    python scripts/awarding/run_awarding_test_drive.py \\
        --pending-file scripts/awarding/sample_pending.json \\
        --shipping-fee-unit PER_BOARD --price-cap-basis UNIT_PRICE

2) 가짜 Backend 로 조회 · 전송까지 (다른 터미널에서 mock_backend.py 를 먼저 띄운다)
    BACKEND_INTERNAL_API_KEY=local-test-key python scripts/awarding/run_awarding_test_drive.py \\
        --backend-url http://127.0.0.1:18080 \\
        --shipping-fee-unit PER_BOARD --price-cap-basis UNIT_PRICE --send

3) 실제 dev Backend — 먼저 `--send` 없이 조회 · 판정만 확인한다.
   ⛔ `--send` 는 실제 board · product · demand 상태를 바꾸고 공동구매를 만든다.

- 키는 환경변수 `BACKEND_INTERNAL_API_KEY` 로만 받는다 (명령줄에 남기지 않는다)
- 필수 판정 필드가 빠진 board 는 판정하지 않고 보고서 `skipped` 에 계약 오류로 남는다 (명세 10-1.4절)
- 종료 코드: 0 정상 · 1 실행 실패 · 2 키 없음 · 3 조회는 됐는데 한 건도 판정하지 못함
  · 4 전송은 됐는데 Backend 가 반영하지 않은 board 가 있음 (stale — 묶음 롤백일 수 있다)
- 배송비 단위 · 가격 상한 기준은 PM 결정 전이다. 명령줄 값은 시험용이며 보고서 `policy` 에 남는다
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from moongcheap_ai.seller_matching.awarding_batch import (
    fetch_pending,
    post_result,
    run_once,
)
from moongcheap_ai.seller_matching.offer_ranking import (
    PRICE_CAP_BASES,
    SHIPPING_FEE_UNITS,
    RankingPolicy,
)

KST = timezone(timedelta(hours=9))
KEY_ENV = "BACKEND_INTERNAL_API_KEY"


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--pending-file", type=Path, help="조회 응답 JSON 파일")
    source.add_argument("--backend-url", help="Backend 주소 (예: http://127.0.0.1:18080)")
    parser.add_argument("--size", type=int, default=50, help="조회 size (1~100)")
    parser.add_argument("--shipping-fee-unit", required=True, choices=SHIPPING_FEE_UNITS)
    parser.add_argument("--price-cap-basis", required=True, choices=PRICE_CAP_BASES)
    parser.add_argument("--send", action="store_true", help="결과를 실제로 전송한다 (--backend-url 필요)")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--report", type=Path, default=None, help="보고서 JSON 저장 경로")
    args = parser.parse_args(argv)
    if args.send and not args.backend_url:
        parser.error("--send 는 --backend-url 과 함께 써야 한다")
    return args


def _print_summary(report: dict) -> None:
    print(f"\n정책: {report['policy']}  hasNext={report['hasNext']}")
    for board in report["boards"]:
        winner = board["awardedProductId"]
        print(f"\n[board {board['boardId']}] {board['outcome']}" + (f" → product {winner}" if winner else ""))
        if board["skippedChecks"]:
            print(f"  검사 안 함(입력 없음): {', '.join(board['skippedChecks'])}")
        for e in board["evaluations"]:
            mark = "★" if e["productId"] == winner else " "
            rank = f"{e['rank']}위" if e["rank"] else "탈락"
            print(f"  {mark} {e['productId']:>6} {rank:>4} score {e['score']} 총액 {e['totalCost']:,}원 | {e['reason']}")
    for item in report["skipped"]:
        print(f"\n[board {item['boardId']}] 건너뜀 — {item['reason']}")
    counts = report["counts"]
    print(f"\n조회 {counts['fetched']}건 · 판정 {counts['judged']}건(낙찰 {counts['awarded']}) · 건너뜀 {counts['skipped']}건")
    print(f"전송 요청 {len(report['requests'])}건 · 전송 {'함' if report['sent'] else '안 함 (dry run)'}")
    for response in report["responses"]:
        print(f"  응답: {response}")
    reflection = report.get("reflection")
    if reflection is not None:
        print(f"  반영 {reflection['appliedCount']}건 · 미반영(stale) {reflection['staleRejectedCount']}건 / 보낸 board {reflection['submittedBoards']}건")


def _write_report(path: Path | None, report: dict) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n보고서: {path}")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    policy = RankingPolicy(shipping_fee_unit=args.shipping_fee_unit, price_cap_basis=args.price_cap_basis)
    send = None

    if args.pending_file:
        payload = json.loads(args.pending_file.read_text(encoding="utf-8"))
    else:
        import requests

        key = os.environ.get(KEY_ENV, "")
        if not key.strip():
            print(f"{KEY_ENV} 환경변수가 비어 있다", file=sys.stderr)
            return 2
        try:
            payload = fetch_pending(args.backend_url, key, size=args.size, timeout_seconds=args.timeout, http_get=requests.get)
        except (RuntimeError, ValueError, requests.RequestException) as error:
            print(f"조회 실패: {error}", file=sys.stderr)
            return 1
        if args.send:

            def send(request: dict) -> dict:
                return post_result(args.backend_url, key, request, timeout_seconds=args.timeout, http_post=requests.post)

    try:
        report = run_once(
            payload,
            policy,
            now=datetime.now(KST),
            send=send,
        )
    except Exception as error:  # noqa: BLE001 — 네트워크 오류 포함. 한 줄로 알리고 끝낸다
        # ⛔ 전송 실패는 재시도하지 않는다. 반영되지 않은 board 는 다음 조회에 다시 나온다.
        print(f"실행 실패: {error}", file=sys.stderr)
        return 1
    _print_summary(report)
    counts = report["counts"]
    if counts["fetched"] and not counts["judged"]:
        # 주기 실행에서 조용히 지나가면 안 되는 상태다. 조회는 됐는데 전부 계약 오류다.
        print(f"판정한 board 가 없다 — 조회 {counts['fetched']}건이 모두 건너뛰어졌다", file=sys.stderr)
        _write_report(args.report, report)
        return 3
    reflection = report.get("reflection")
    if reflection is not None and reflection["staleRejectedCount"]:
        # stale 은 이미 처리된 board 일 수도, 10개 묶음이 통째로 롤백된 것일 수도 있다. 응답으로는 구분되지 않는다.
        # ⛔ 다시 보내지 않는다. Backend 조회·이력으로 확인한다.
        print(
            f"반영되지 않은 board 가 {reflection['staleRejectedCount']}건이다 "
            f"(보낸 {reflection['submittedBoards']}건 중 반영 {reflection['appliedCount']}건) — Backend 이력을 확인한다",
            file=sys.stderr,
        )
        _write_report(args.report, report)
        return 4
    _write_report(args.report, report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
