import importlib.util
import json
from pathlib import Path

import pandas as pd


def test_resume_only_pending_and_report_missing_ids(tmp_path, monkeypatch):
    script = Path(__file__).resolve().parents[1] / "scripts/facet/translate_kuaisearch.py"
    spec = importlib.util.spec_from_file_location("translation_runner", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = tmp_path / "input.parquet"
    output = tmp_path / "output.parquet"
    frame = pd.DataFrame({"source_record_id": ["1", "2", "3"], "query_raw": ["a", "b", "c"]})
    frame.to_parquet(source)
    frame.assign(query_translated=["cached", "", ""]).to_parquet(output)
    batches = []

    def translate(rows, *args):
        batches.append(rows)
        return [{"source_record_id": "2", "query_translated": "translated"}]

    monkeypatch.setattr(module, "_translate_batch", translate)
    monkeypatch.setattr("sys.argv", [str(script), "--input", str(source), "--output", str(output)])
    module.main()
    assert [row["source_record_id"] for row in batches[0]] == ["2", "3"]
    result = pd.read_parquet(output)
    assert result.query_translated.tolist() == ["cached", "translated", ""]
    report = json.loads(output.with_suffix(".report.json").read_text())
    assert report["status"] == "COMPLETED_WITH_WARNINGS"
    assert report["failures"] == 1
    assert report["remaining"] == 1

    monkeypatch.setattr(module, "_translate_batch", lambda *args: [{"source_record_id": "3", "query_translated": "last"}])
    module.main()
    module.main()
    report = json.loads(output.with_suffix(".report.json").read_text())
    assert report["status"] == "COMPLETED"
    assert report["calls"] == 0
    assert report["remaining"] == 0
