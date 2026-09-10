from pathlib import Path

from scripts.purchase.probe_foodpolis_openapi import probe


def test_probe_does_not_call_without_documented_endpoint(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FOODPOLIS_API_KEY", "secret-that-must-not-be-written")
    result = probe(output=tmp_path / "probe.md")
    assert result["status"] == "FOODPOLIS_OPEN_API_ENDPOINT_NOT_FOUND"
    text = (tmp_path / "probe.md").read_text(encoding="utf-8")
    assert "secret-that-must-not-be-written" not in text
    assert result["api_key_configured"] is True
