"""시험 운전 스크립트를 가짜 Backend 에 실제 HTTP 로 붙여 본다."""

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


def test_send_requires_backend_url():
    with pytest.raises(SystemExit):
        _load("run_awarding_test_drive").main(["--pending-file", str(SAMPLE), *ARGS, "--send"])
