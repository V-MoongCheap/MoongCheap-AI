import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest


@pytest.fixture
def runner(monkeypatch):
    directory = Path(__file__).resolve().parents[1] / "scripts/facet"
    monkeypatch.syspath_prepend(str(directory))
    spec = importlib.util.spec_from_file_location("repair_runner", directory / "repair_kuaisearch_translation.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_quality_rejects_placeholders_and_product_changes(runner):
    assert "PLACEHOLDER" in runner.quality_flags("猫粮", "...")
    assert "TERM_MISMATCH:菠萝" in runner.quality_flags("菠萝软糖", "바나나 젤리")
    assert not runner.quality_flags("菠萝软糖", "파인애플 젤리")
    assert "NUMBER_MISSING" in runner.quality_flags("猫粮2袋", "고양이 사료")


def test_source_grounded_normalization_corrects_known_terms(runner):
    value, changes = runner.normalize_translation("菠萝圈软糖", "바나나 소프트 글루")
    assert value == "파인애플 젤리"
    assert changes == ["菠萝->파인애플", "软糖->젤리"]
    value, changes = runner.normalize_translation("防晒口罩", "방향제 마스크")
    assert value == "자외선 차단 마스크"
    assert changes == ["防晒->자외선 차단"]
    value, _ = runner.normalize_translation("茯苓", "茯苓")
    assert value == "복령"


def test_nontranslatable_sources_and_chinese_numbers(runner):
    assert runner.is_source_nontranslatable("https://example.com/item")
    assert runner.is_source_nontranslatable("AB-001")
    assert not runner.is_source_nontranslatable("고양이 사료")
    assert runner.numeric_tokens("四00三") == {"4003"}
    assert "NUMBER_MISSING" not in runner.quality_flags("压缩饼干军款四00三厂", "압축 비스킷 군용 4003 공장")


def test_repair_preserves_original_and_resumes(runner, tmp_path, monkeypatch):
    source = tmp_path / "source.parquet"
    output = tmp_path / "v2.parquet"
    frame = pd.DataFrame({"source_record_id": ["1", "2"], "query_raw": ["猫粮", "面膜"], "query_translated": ["...", "..."]})
    frame.to_parquet(source, index=False)
    original = source.read_bytes()
    monkeypatch.setattr("sys.argv", ["repair", "--input", str(source), "--output", str(output), "--passes", "1"])
    monkeypatch.setattr(runner, "_translate_batch", lambda *args: [{"source_record_id": "0", "query_translated": "고양이 사료"}])
    runner.main()
    saved = pd.read_parquet(output)
    assert saved.query_translated.tolist() == ["고양이 사료", "..."]
    assert saved.repair_status.tolist() == ["AUTOMATED_CHECKS_PASSED", "NEEDS_REVIEW"]
    assert source.read_bytes() == original
    calls = []

    def translate(rows, *args):
        calls.extend(rows)
        return [{"source_record_id": "1", "query_translated": "마스크팩"}]

    monkeypatch.setattr(runner, "_translate_batch", translate)
    runner.main()
    assert len(calls) == 1
    assert calls[0]["source_record_id"] == "1"
    report = json.loads(output.with_suffix(".report.json").read_text())
    assert report["remaining_blocking"] == 0
    assert pd.read_parquet(output).translation_original.tolist() == ["...", "..."]
    frame.assign(query_raw=["狗粮", "菠萝软糖"]).to_parquet(source)
    with pytest.raises(ValueError, match="snapshot changed"):
        runner.main()


def test_checkpoint_retries_transient_windows_lock(runner, tmp_path, monkeypatch):
    output = tmp_path / "output.parquet"
    frame = pd.DataFrame({"value": [1]})
    replace = Path.replace
    attempts = []

    def locked_replace(path, target):
        attempts.append(target)
        if len(attempts) < 3:
            raise PermissionError("Reader still holds file")
        return replace(path, target)

    monkeypatch.setattr(Path, "replace", locked_replace)
    monkeypatch.setattr(runner.time, "sleep", lambda _: None)
    runner.checkpoint(frame, output)
    assert len(attempts) == 3
    assert pd.read_parquet(output).value.tolist() == [1]


def test_translation_specialist_uses_plain_text_and_preserves_id(runner, monkeypatch):
    import io
    import translate_kuaisearch

    requests = []

    def respond(request, timeout):
        body = json.loads(request.data)
        requests.append(body)
        if "source_record_id" not in body.get("messages", [{}])[0].get("content", ""):
            return io.BytesIO(json.dumps({"message": {"content": "고양이 사료"}, "done_reason": "stop"}).encode())
        return io.BytesIO(json.dumps({"message": {"content": json.dumps({"translations": [{"source_record_id": "id-1", "query_translated": "고양이 사료"}, {"source_record_id": "id-1", "query_translated": "고양이 사료"}]})}, "done_reason": "stop"}).encode())

    monkeypatch.setattr(translate_kuaisearch.urllib.request, "urlopen", respond)
    rows = [{"source_record_id": "id-1", "query_raw": "猫粮"}]
    result = translate_kuaisearch._translate_batch(rows, "translategemma:4b", "http://localhost:11434", 120)
    assert result == [{"source_record_id": "id-1", "query_translated": "고양이 사료"}]
    assert requests[0]["messages"][0]["content"].endswith("\n\n\n猫粮")
    assert "format" not in requests[0]
    assert translate_kuaisearch._translate_batch(rows * 2, "translategemma:4b", "http://localhost:11434", 120)
