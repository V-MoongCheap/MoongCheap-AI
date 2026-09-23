"""시험 운전 스크립트를 가짜 Backend 에 실제 HTTP 로 붙여 본다."""

import ast
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
