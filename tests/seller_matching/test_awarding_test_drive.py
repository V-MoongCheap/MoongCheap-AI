"""시험 운전 스크립트를 가짜 Backend 에 실제 HTTP 로 붙여 본다."""

import ast
import copy
import importlib.util
import json
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "scripts" / "awarding" / "sample_pending.json"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / "awarding" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def backend():
    mock = _load("mock_backend")
    server = mock.serve(SAMPLE, "test-key", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server, f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


ARGS = ["--shipping-fee-unit", "PER_BOARD", "--price-cap-basis", "UNIT_PRICE"]


def test_file_mode_never_needs_a_key(tmp_path, monkeypatch):
    monkeypatch.delenv("BACKEND_INTERNAL_API_KEY", raising=False)
    report = tmp_path / "report.json"

    code = _load("run_awarding_test_drive").main(["--pending-file", str(SAMPLE), *ARGS, "--report", str(report)])

    data = json.loads(report.read_text(encoding="utf-8"))
    assert code == 0
    assert data["sent"] is False
    assert [b["boardId"] for b in data["boards"]] == [1001, 1002, 1003]
    assert data["skipped"] == [{"boardId": 1004, "reason": "missing required field: products[0].shippingFee"}]


def test_wrong_key_fails_cleanly(backend, monkeypatch, capsys):
    _, url = backend
    monkeypatch.setenv("BACKEND_INTERNAL_API_KEY", "wrong")

    code = _load("run_awarding_test_drive").main(["--backend-url", url, *ARGS])

    assert code == 1
    assert "401" in capsys.readouterr().err


def test_send_applies_boards_and_removes_them_from_pending(backend, monkeypatch, tmp_path):
    server, url = backend
    monkeypatch.setenv("BACKEND_INTERNAL_API_KEY", "test-key")
    drive = _load("run_awarding_test_drive")
    report = tmp_path / "report.json"

    code = drive.main(["--backend-url", url, *ARGS, "--send", "--report", str(report)])

    data = json.loads(report.read_text(encoding="utf-8"))
    assert code == 0
    assert data["responses"] == [{"status": "APPLIED", "appliedCount": 3, "staleRejectedCount": 0}]
    assert set(server.backend.pending) == {1004}  # 계약 오류 board 는 판정하지 않아 그대로 남는다
    assert server.backend.applied[1001]["evaluations"][0]["isAwarded"] is True


def test_exit_code_signals_that_nothing_could_be_judged(tmp_path, monkeypatch, capsys):
    """모든 board 가 계약 오류면 주기 실행에서 알아챌 수 있어야 한다."""
    monkeypatch.delenv("BACKEND_INTERNAL_API_KEY", raising=False)
    broken = json.loads(SAMPLE.read_text(encoding="utf-8"))
    broken["boards"] = [b for b in broken["boards"] if b["boardId"] == 1004]
    payload = tmp_path / "pending.json"
    payload.write_text(json.dumps(broken, ensure_ascii=False), encoding="utf-8")

    code = _load("run_awarding_test_drive").main(["--pending-file", str(payload), *ARGS])

    assert code == 3
    assert "판정한 board 가 없다" in capsys.readouterr().err


def test_exit_code_is_zero_when_there_is_nothing_to_judge(tmp_path, monkeypatch):
    monkeypatch.delenv("BACKEND_INTERNAL_API_KEY", raising=False)
    empty = json.loads(SAMPLE.read_text(encoding="utf-8")) | {"boards": [], "size": 0}
    payload = tmp_path / "empty.json"
    payload.write_text(json.dumps(empty, ensure_ascii=False), encoding="utf-8")

    assert _load("run_awarding_test_drive").main(["--pending-file", str(payload), *ARGS]) == 0


def test_stale_response_does_not_pass_as_success(backend, monkeypatch, tmp_path, capsys):
    """묶음 롤백도 staleRejectedCount 로 온다. 주기 실행에서 조용히 지나가면 안 된다."""
    server, url = backend
    monkeypatch.setenv("BACKEND_INTERNAL_API_KEY", "test-key")
    server.backend.apply = lambda body: (200, {"status": "APPLIED", "appliedCount": 0, "staleRejectedCount": len(body["results"])})
    report = tmp_path / "report.json"

    code = _load("run_awarding_test_drive").main(["--backend-url", url, *ARGS, "--send", "--report", str(report)])

    assert code == 4
    assert "반영되지 않은 board" in capsys.readouterr().err
    assert json.loads(report.read_text(encoding="utf-8"))["reflection"]["staleRejectedCount"] == 3


def test_container_smoke_does_not_rely_on_assert():
    """`python -O` 는 assert 를 지운다. 컨테이너 시험이 거짓 PASS 하면 안 된다."""
    source = (ROOT / "scripts" / "awarding" / "container_smoke.py").read_text(encoding="utf-8")

    lines = [node.lineno for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Assert)]

    assert lines == []


def test_send_requires_backend_url():
    with pytest.raises(SystemExit):
        _load("run_awarding_test_drive").main(["--pending-file", str(SAMPLE), *ARGS, "--send"])


def test_every_dockerfile_has_a_dockerignore():
    """빌드 컨텍스트 제한은 CI(Kaniko)에서도 남아야 한다. 스크립트만으로는 CI 에 적용되지 않는다."""
    docker_dir = ROOT / "docker"

    missing = [f.name for f in sorted(docker_dir.glob("Dockerfile.*")) if not f.name.endswith(".dockerignore")
               and not (docker_dir / f"{f.name}.dockerignore").exists()]

    assert missing == []


def test_summary_survives_a_report_without_reflection():
    """보고서를 다른 경로로 만들었을 때 요약이 죽지 않는다."""
    drive = _load("run_awarding_test_drive")
    report = {"policy": {}, "hasNext": False, "boards": [], "skipped": [], "requests": [], "sent": False,
              "responses": [], "counts": {"fetched": 0, "judged": 0, "skipped": 0, "awarded": 0}}

    drive._print_summary(report)


def _dockerfile_stages():
    """단계 이름 → (부모 단계, 본문). 부모가 없으면 None."""
    stages, current = {}, None
    for line in (ROOT / "docker" / "Dockerfile.awarding").read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("FROM "):
            source, _, name = stripped[5:].partition(" AS ")
            current = (name or source).strip()
            stages[current] = [source.strip(), []]
        elif current:
            stages[current][1].append(stripped)
    return stages


def _lines_of(stages, name):
    """상속까지 따라간 누적 본문. 마지막 단계 텍스트만 보면 base 로 옮긴 COPY 를 놓친다."""
    parent, body = stages[name]
    inherited = _lines_of(stages, parent) if parent in stages else []
    return inherited + body


def test_deploy_stage_of_the_awarding_image_has_no_test_code():
    """Mock 서버와 loopback 시험은 시험 단계에만 둔다. 배포 이미지는 배치만 담는다."""
    stages = _dockerfile_stages()
    deploy = " ".join(_lines_of(stages, list(stages)[-1]))
    test_stage = " ".join(_lines_of(stages, "test"))

    assert "mock_backend.py" not in deploy
    assert "container_smoke.py" not in deploy
    assert "container_smoke.py" in test_stage
    assert "run_awarding_test_drive.py" in deploy


def test_a_single_unreflected_board_is_not_silent(backend, monkeypatch, tmp_path, capsys):
    """미반영이 1건뿐일 때도 알린다. 경계에서 조용해지면 주기 실행에서 못 본다."""
    server, url = backend
    monkeypatch.setenv("BACKEND_INTERNAL_API_KEY", "test-key")
    server.backend.apply = lambda body: (200, {"status": "APPLIED", "appliedCount": len(body["results"]) - 1,
                                               "staleRejectedCount": 1})
    report = tmp_path / "report.json"

    code = _load("run_awarding_test_drive").main(["--backend-url", url, *ARGS, "--send", "--report", str(report)])

    assert code == 4
    assert "반영되지 않은 board 가 1건" in capsys.readouterr().err
    assert json.loads(report.read_text(encoding="utf-8"))["reflection"] == {
        "submittedBoards": 3, "appliedCount": 2, "staleRejectedCount": 1}


def test_hundred_boards_use_two_http_posts(backend, monkeypatch, tmp_path):
    server, url = backend
    seed = copy.deepcopy(server.backend.pending[1001])
    server.backend.pending = {i: dict(copy.deepcopy(seed), boardId=i) for i in range(1, 101)}
    calls = []
    original = server.backend.apply

    def apply(body):
        calls.append(len(body["results"]))
        return original(body)

    server.backend.apply = apply
    monkeypatch.setenv("BACKEND_INTERNAL_API_KEY", "test-key")
    report_path = tmp_path / "report.json"
    code = _load("run_awarding_test_drive").main([
        "--backend-url", url, "--size", "100", *ARGS, "--send", "--report", str(report_path)])
    assert code == 0
    assert calls == [50, 50]
    assert server.backend.pending == {}
    assert json.loads(report_path.read_text())["reflection"] == {
        "submittedBoards": 100, "appliedCount": 100, "staleRejectedCount": 0}


@pytest.mark.parametrize("failure", ["timeout", "invalid_response", "http_500"])
def test_partial_send_failure_saves_confirmed_and_unknown_requests(
    backend, monkeypatch, tmp_path, capsys, failure,
):
    import requests

    server, url = backend
    seed = copy.deepcopy(server.backend.pending[1001])
    server.backend.pending = {i: dict(copy.deepcopy(seed), boardId=i) for i in range(1, 101)}
    monkeypatch.setenv("BACKEND_INTERNAL_API_KEY", "test-key")
    calls = []
    original_post = requests.post

    def post(*args, **kwargs):
        calls.append(kwargs["json"])
        response = original_post(*args, **kwargs)
        if len(calls) == 2:
            # 서버가 실제 반영한 뒤 응답만 유실/변형: 실패를 미반영으로 단정하면 안 된다.
            if failure == "timeout":
                raise requests.Timeout("do-not-log-response-or-secret")
            if failure == "invalid_response":
                response._content = b'{"status": "do-not-log-response-or-secret"}'
            else:
                response.status_code = 500
                response._content = b"do-not-log-response-or-secret"
        return response

    monkeypatch.setattr(requests, "post", post)
    report_path = tmp_path / "partial.json"
    code = _load("run_awarding_test_drive").main([
        "--backend-url", url, "--size", "100", *ARGS, "--send", "--report", str(report_path)])

    assert code == 1
    assert len(calls) == 2
    assert server.backend.pending == {}  # 오류여도 실제 반영은 100건이다.
    assert report_path.exists(), "전송 도중 실패해도 부분 보고서가 필요하다"
    report = json.loads(report_path.read_text())
    assert report["sent"] is True  # 시도했다는 뜻이지 반영 완료라는 뜻이 아니다.
    assert report["reflection"] is None
    assert report["confirmedReflection"] == {
        "submittedBoards": 50, "appliedCount": 50, "staleRejectedCount": 0}
    assert report["sendProgress"] == {
        "status": "unconfirmed",
        "requests": [
            {"requestIndex": 1, "boardIds": list(range(1, 51)), "status": "confirmed"},
            {"requestIndex": 2, "boardIds": list(range(51, 101)), "status": "unconfirmed"},
        ],
    }
    output = capsys.readouterr()
    assert "Backend" in output.err
    assert "do-not-log-response-or-secret" not in output.err + output.out + report_path.read_text()


def test_mock_enforces_50_results_but_allows_over_50_evaluations():
    mock = _load("mock_backend")
    body = {
        "schemaVersion": "awarding-result.v0.1", "ruleVersion": "test",
        "plannedAt": "2026-09-23T16:00:00+09:00",
        "results": [{"boardId": i, "judgedAt": "2026-09-23T16:00:00",
                     "evaluations": [{"productId": 1, "score": 0.0, "isAwarded": False}]}
                    for i in range(51)],
    }
    assert mock._invalid(body) == "results must have 1..50 items"
    body["results"] = body["results"][:50]
    assert mock._invalid(body) is None
    body["results"][0]["evaluations"] = [
        {"productId": i, "score": 0.0, "isAwarded": False} for i in range(51)]
    assert mock._invalid(body) is None
    body["results"][0]["evaluations"] = []
    assert mock._invalid(body) is not None


@pytest.mark.parametrize("report_mode", ["omitted", "unwritable"])
def test_failed_send_still_logs_progress_without_a_writable_report(
    backend, monkeypatch, tmp_path, capsys, report_mode,
):
    server, url = backend
    monkeypatch.setenv("BACKEND_INTERNAL_API_KEY", "test-key")
    calls = []

    def apply(body):
        calls.append(body)
        return 200, {"status": "invalid"}

    server.backend.apply = apply
    # 디렉터리를 파일 경로로 지정하면 root 권한 여부와 관계없이 쓰기에 실패한다.
    report_args = [] if report_mode == "omitted" else ["--report", str(tmp_path)]
    code = _load("run_awarding_test_drive").main(["--backend-url", url, *ARGS, "--send", *report_args])
    assert code == 1
    assert len(calls) == 1
    stderr = capsys.readouterr().err
    progress = json.loads(stderr.splitlines()[1])
    assert progress["sendProgress"]["requests"] == [
        {"requestIndex": 1, "boardIds": [1001, 1002, 1003], "status": "unconfirmed"}]
    assert progress["confirmedReflection"]["submittedBoards"] == 0
    if report_mode == "unwritable":
        assert "부분 보고서 저장 실패" in stderr


def test_zero_demand_stays_unposted_until_policy_is_confirmed(backend, monkeypatch):
    server, url = backend
    seed = copy.deepcopy(server.backend.pending[1001])
    seed["totalQuantity"] = 0
    server.backend.pending = {1001: seed}
    monkeypatch.setenv("BACKEND_INTERNAL_API_KEY", "test-key")
    assert _load("run_awarding_test_drive").main(["--backend-url", url, *ARGS, "--send"]) == 3
    assert server.backend.applied == {}
    assert set(server.backend.pending) == {1001}
