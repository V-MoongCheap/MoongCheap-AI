"""낙찰 연동 시험 운전용 가짜 Backend.

Backend develop 의 낙찰 API 동작을 좁게 흉내 낸다 (2026-09-17 코드 열람 기준).

- `/api/awarding/**` 는 `X-Internal-Api-Key` 가 맞지 않으면 401 `COMMON_401`
- `GET /api/awarding/internal/pending?size=` — 1~100, 기본 50. 대기 board 를 순서대로 최대 size 개, `hasNext`
- `POST /api/awarding/internal/result` — 형식 위반은 400. 그 밖에는 200 + `appliedCount` · `staleRejectedCount`
  · 이미 처리된 board → stale
  · evaluations 가 그 board 의 상품 전건과 다름 → stale
  · 반영된 board 는 대기 목록에서 빠진다

⛔ 실제 Backend 의 10개 묶음 트랜잭션 · DB 상태 전이 · 공동구매 생성은 흉내 내지 않는다.

    python scripts/awarding/mock_backend.py --pending-file scripts/awarding/sample_pending.json --key local-test-key
"""

from __future__ import annotations

import argparse
import json
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# 이 파일은 패키지를 import 하지 않고 단독 실행할 수 있어야 해서 KST 를 따로 둔다.
KST = timezone(timedelta(hours=9))
UNAUTHORIZED = {"success": False, "data": None, "error": {"code": "COMMON_401", "message": "인증이 필요합니다.", "fieldErrors": []}}


class MockAwardingBackend:
    def __init__(self, pending: dict, key: str) -> None:
        self.key = key
        self.lock = threading.Lock()
        self.pending = {board["boardId"]: board for board in pending["boards"]}
        self.applied: dict[int, dict] = {}

    def page(self, size: int) -> dict:
        with self.lock:
            boards = list(self.pending.values())
        return {
            "schemaVersion": "awarding-pending.v0.1",
            "fetchedAt": datetime.now(KST).replace(tzinfo=None).isoformat(timespec="seconds"),  # Backend 는 LocalDateTime
            "boards": boards[:size],
            "size": len(boards[:size]),
            "hasNext": len(boards) > size,
        }

    def apply(self, body: object) -> tuple[int, dict]:
        problem = _invalid(body)
        if problem:
            return 400, {"success": False, "error": {"code": "COMMON_400", "message": problem}}
        applied = stale = 0
        with self.lock:
            for result in body["results"]:
                board = self.pending.get(result["boardId"])
                expected = {p["productId"] for p in board["products"]} if board else None
                sent = {e["productId"] for e in result["evaluations"]}
                if board is None or sent != expected:
                    stale += 1
                    continue
                self.applied[result["boardId"]] = result
                del self.pending[result["boardId"]]
                applied += 1
        return 200, {"status": "APPLIED", "appliedCount": applied, "staleRejectedCount": stale}


def _invalid(body: object) -> str | None:
    """Backend `AwardingResultRequestDto` 의 Bean Validation 을 옮겼다."""
    if not isinstance(body, dict):
        return "body must be an object"
    for key in ("schemaVersion", "plannedAt", "ruleVersion"):
        if not isinstance(body.get(key), str) or not body[key]:
            return f"{key} is required"
    try:
        if datetime.fromisoformat(body["plannedAt"]).tzinfo is None:
            return "plannedAt must carry an offset"
    except ValueError:
        return "plannedAt must be ISO-8601"
    results = body.get("results")
    if not isinstance(results, list) or not 1 <= len(results) <= 100:
        return "results must have 1..100 items"
    if len({r.get("boardId") for r in results}) != len(results):
        return "results의 boardId는 중복될 수 없습니다"
    for result in results:
        try:
            if datetime.fromisoformat(result["judgedAt"]).tzinfo is not None:
                return "judgedAt must be a LocalDateTime (no offset)"
        except (KeyError, TypeError, ValueError):
            return "judgedAt is required"
        evaluations = result.get("evaluations")
        if not isinstance(evaluations, list) or not 1 <= len(evaluations) <= 50:
            return "evaluations must have 1..50 items"
        if len({e.get("productId") for e in evaluations}) != len(evaluations):
            return "evaluations의 productId는 중복될 수 없습니다"
        if sum(e.get("isAwarded") is True for e in evaluations) > 1:
            return "낙찰(isAwarded=true) 항목은 최대 1개까지 허용됩니다"
        for e in evaluations:
            score = e.get("score")
            if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= score <= 1 or round(score, 4) != score:
                return "score must be 0.0000..1.0000 with up to 4 decimals"
            if not isinstance(e.get("isAwarded"), bool):
                return "isAwarded is required"
            if e.get("reason") is not None and len(e["reason"]) > 500:
                return "reason must be at most 500 chars"
    return None


def make_handler(backend: MockAwardingBackend):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, payload: dict) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _authorized(self) -> bool:
            if self.headers.get("X-Internal-Api-Key") != backend.key:
                self._send(401, UNAUTHORIZED)
                return False
            return True

        def do_GET(self) -> None:
            url = urlparse(self.path)
            if url.path != "/api/awarding/internal/pending":
                return self._send(404, {"error": "not found"})
            if not self._authorized():
                return None
            raw = parse_qs(url.query).get("size", ["50"])[0]
            if not raw.isdigit() or not 1 <= int(raw) <= 100:
                return self._send(400, {"success": False, "error": {"code": "COMMON_400", "message": "size must be 1..100"}})
            return self._send(200, backend.page(int(raw)))

        def do_POST(self) -> None:
            if urlparse(self.path).path != "/api/awarding/internal/result":
                return self._send(404, {"error": "not found"})
            if not self._authorized():
                return None
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"null")
            except json.JSONDecodeError:
                return self._send(400, {"success": False, "error": {"code": "COMMON_400", "message": "invalid JSON"}})
            status, payload = backend.apply(body)
            return self._send(status, payload)

        def log_message(self, format: str, *args: object) -> None:
            print(f"[mock-backend] {self.command} {self.path} -> {args[1] if len(args) > 1 else ''}")

    return Handler


def serve(pending_file: Path, key: str, host: str = "127.0.0.1", port: int = 18080) -> ThreadingHTTPServer:
    backend = MockAwardingBackend(json.loads(pending_file.read_text(encoding="utf-8")), key)
    server = ThreadingHTTPServer((host, port), make_handler(backend))
    server.backend = backend  # type: ignore[attr-defined]
    return server


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pending-file", type=Path, default=Path(__file__).with_name("sample_pending.json"))
    parser.add_argument("--key", required=True, help="이 가짜 서버가 요구할 X-Internal-Api-Key 값")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18080)
    args = parser.parse_args()
    server = serve(args.pending_file, args.key, args.host, args.port)
    print(f"mock awarding backend on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
