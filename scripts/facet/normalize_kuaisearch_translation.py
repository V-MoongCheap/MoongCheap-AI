"""Apply source-grounded terminology normalization without model calls."""

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from translate_kuaisearch import normalize_translation


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("data/interim/facet_evidence/kuaiseach_health_queries_ko.parquet"))
    parser.add_argument("--output", type=Path, default=Path("data/interim/facet_evidence/kuaiseach_health_queries_ko_normalized_v2.parquet"))
    args = parser.parse_args()
    source_hash = hashlib.sha256(args.input.read_bytes()).hexdigest()
    frame = pd.read_parquet(args.input).fillna("")
    frame["query_translated_original"] = frame.query_translated
    pairs = [normalize_translation(str(row.query_raw), str(row.query_translated)) for row in frame.itertuples()]
    frame["query_translated"] = [pair[0] for pair in pairs]
    frame["normalization_changes"] = ["|".join(pair[1]) for pair in pairs]
    frame["normalization_status"] = frame.normalization_changes.map(lambda value: "NORMALIZED" if value else "UNCHANGED")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(args.output, index=False)
    frame.to_csv(args.output.with_name(args.output.stem + "_preview.csv"), index=False, encoding="utf-8-sig")
    report = {"status": "COMPLETED", "rows": len(frame), "normalized_rows": int(frame.normalization_status.eq("NORMALIZED").sum()), "source_sha256": source_hash, "model_calls": 0, "accuracy": None}
    args.output.with_suffix(".report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
