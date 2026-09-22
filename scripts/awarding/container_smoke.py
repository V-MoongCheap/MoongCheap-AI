"""컨테이너 내 loopback Mock 시험. 실제 Backend 주소/키를 입력받지 않는다.

Docker --network none에서도 실행 가능하다. Mock은 묶음 롤백/DB 전이를 재현하지 않는다.
⛔ 검사에 `assert` 를 쓰지 않는다. `python -O` 가 지워 거짓 PASS 가 되기 때문이다.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import threading
from datetime import UTC, datetime
from http.server import ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory

import requests
import run_awarding_test_drive as drive
from mock_backend import MockAwardingBackend, make_handler

from moongcheap_ai.seller_matching.awarding_batch import post_result, run_once
from moongcheap_ai.seller_matching.offer_ranking import RankingPolicy

SAMPLE = Path(__file__).with_name("sample_pending.json")
KEY = "local-smoke-key-not-a-secret"
POLICY_ARGS = ["--shipping-fee-unit", "PER_BOARD", "--price-cap-basis", "UNIT_PRICE"]


def require(condition: object, message: str) -> None:
    """`assert` 대신 쓴다. 최적화 모드에서도 지워지지 않는다."""
    if not condition:
        raise AssertionError(message)


@contextlib.contextmanager
def local_server(payload, *, broken_response=False, stale_response=False):
    backend = MockAwardingBackend(payload, KEY)
    normal_handler = make_handler(backend)

    class BrokenHandler(normal_handler):
        posts = 0

        def do_POST(self):
            type(self).posts += 1
            self._send(200, {})

    class StaleHandler(normal_handler):
        posts = 0

        def do_POST(self):
            type(self).posts += 1
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            # 실제 Backend 는 묶음 롤백도 stale 로 합산한다. 응답만으로는 정상 중복과 구분되지 않는다.
            self._send(200, {"status": "APPLIED", "appliedCount": 0, "staleRejectedCount": len(body.get("results", []))})

    handler = BrokenHandler if broken_response else StaleHandler if stale_response else normal_handler
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield backend, f"http://127.0.0.1:{server.server_port}", handler
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def invoke(args, expected):
    output, error = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
        code = drive.main(args)
    if code != expected:
        raise AssertionError(f"expected exit {expected}, got {code}: {output.getvalue()} {error.getvalue()}")
    return error.getvalue()


def check():
    sample = json.loads(SAMPLE.read_text(encoding="utf-8"))
    evidence = {}
    with TemporaryDirectory(prefix="awarding-smoke-") as temp:
        report = Path(temp) / "report.json"
        with local_server(sample) as (backend, url, _):
            args = ["--backend-url", url, *POLICY_ARGS]
            os.environ.pop(drive.KEY_ENV, None)
            invoke(args, 2)
            os.environ[drive.KEY_ENV] = "wrong-smoke-key"
            error = invoke(args, 1)
            require("401" in error and "wrong-smoke-key" not in error, f"키 오류 처리가 예상과 다르다: {error}")
            evidence["authentication"] = "missing key exit 2 / wrong key 401 exit 1"

            os.environ[drive.KEY_ENV] = KEY
            invoke([*args, "--report", str(report)], 0)
            dry = json.loads(report.read_text())
            require(not dry["sent"], "dry run 인데 sent 가 참이다")
            require(dry["reflection"] is None, "전송하지 않았는데 반영 요약이 있다")
            require(not backend.applied and len(backend.pending) == 4, "dry run 이 Mock 상태를 바꿨다")
            evidence["dry_run"] = dry["counts"]

            invoke([*args, "--send", "--report", str(report)], 0)
            sent = json.loads(report.read_text())
            require(
                sent["responses"] == [{"status": "APPLIED", "appliedCount": 3, "staleRejectedCount": 0}],
                f"전송 응답이 예상과 다르다: {sent['responses']}",
            )
            require(
                sent["reflection"] == {"submittedBoards": 3, "appliedCount": 3, "staleRejectedCount": 0},
                f"반영 요약이 예상과 다르다: {sent['reflection']}",
            )
            require(set(backend.pending) == {1004}, f"대기 목록이 예상과 다르다: {sorted(backend.pending)}")
            require(
                [e["isAwarded"] for e in backend.applied[1001]["evaluations"]].count(True) == 1,
                "board 1001 의 낙찰이 1건이 아니다",
            )
            require(all(not e["isAwarded"] for e in backend.applied[1002]["evaluations"]), "board 1002 는 유찰이어야 한다")
            evidence["send"] = sent["responses"]
            # 명시적인 중복 시험이며 자동 재시도가 아니다.
            duplicate = post_result(url, KEY, sent["requests"][0], timeout_seconds=2, http_post=requests.post)
            require(
                duplicate == {"status": "APPLIED", "appliedCount": 0, "staleRejectedCount": 3},
                f"중복 전송 응답이 예상과 다르다: {duplicate}",
            )
            evidence["explicit_duplicate_check"] = duplicate

            invoke([*args, "--report", str(report)], 3)
            remaining = json.loads(report.read_text())
            require(
                remaining["counts"] == {"fetched": 1, "judged": 0, "skipped": 1, "awarded": 0},
                f"재조회 건수가 예상과 다르다: {remaining['counts']}",
            )
            evidence["requery"] = remaining["counts"]

        with local_server(sample, broken_response=True) as (_, url, handler):
            error = invoke(["--backend-url", url, *POLICY_ARGS, "--send"], 1)
            require("unconfirmed" in error, f"잘못된 200 을 거절하지 않았다: {error}")
            require(handler.posts == 1, f"POST 가 1회가 아니다: {handler.posts}")
            evidence["invalid_200"] = "exit 1 / unconfirmed / exactly one POST"

        with local_server(sample, stale_response=True) as (_, url, handler):
            error = invoke(["--backend-url", url, *POLICY_ARGS, "--send", "--report", str(report)], 4)
            require("반영되지 않은 board" in error, f"미반영을 알리지 않았다: {error}")
            require(handler.posts == 1, f"POST 가 1회가 아니다: {handler.posts}")
            stale = json.loads(report.read_text())["reflection"]
            require(stale == {"submittedBoards": 3, "appliedCount": 0, "staleRejectedCount": 3}, f"반영 요약이 예상과 다르다: {stale}")
            evidence["stale_not_silent"] = "exit 4 / 경고 / 재전송 없음"

        utc_report = run_once(
            sample,
            RankingPolicy(shipping_fee_unit="PER_BOARD", price_cap_basis="UNIT_PRICE"),
            now=datetime(2026, 9, 18, 5, 5, tzinfo=UTC),
        )
        judged_at = utc_report["requests"][0]["results"][0]["judgedAt"]
        require(judged_at == "2026-09-18T14:05:00", f"judgedAt 이 KST 가 아니다: {judged_at}")
        evidence["utc_to_kst"] = "05:05 UTC -> 14:05 KST"
    return evidence


def main():
    previous = os.environ.get(drive.KEY_ENV)
    try:
        evidence = check()
    finally:
        if previous is None:
            os.environ.pop(drive.KEY_ENV, None)
        else:
            os.environ[drive.KEY_ENV] = previous
    print(json.dumps({"status": "PASS", "scope": "local Mock only", "checks": evidence}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
