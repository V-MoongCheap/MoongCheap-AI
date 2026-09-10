"""Compare a local translation model on the same deterministic review sample."""

import argparse
import json
import time
from pathlib import Path

import pandas as pd

from repair_kuaisearch_translation import quality_flags
from translate_kuaisearch import _translate_batch


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="translategemma:4b")
    parser.add_argument("--input", type=Path, default=Path("data/interim/facet_evidence/kuaiseach_health_queries_ko_v2.parquet"))
    parser.add_argument("--output", type=Path, default=Path("data/reports/kuaisearch_translation_repair_v2/translategemma_pilot.csv"))
    args = parser.parse_args()
    frame = pd.read_parquet(args.input).fillna("")
    known = frame[frame.source_record_id.astype(str).isin(["13304", "208240", "379597", "409567"])]
    accepted = frame[frame.repair_status.eq("AUTOMATED_CHECKS_PASSED")]
    sample = pd.concat([known, accepted.sample(min(20, len(accepted)), random_state=7), frame.sample(20, random_state=42)]).drop_duplicates("query_raw")
    started = time.perf_counter()
    rows = []
    for row in sample.to_dict("records"):
        before = time.perf_counter()
        try:
            response = _translate_batch([{"source_record_id": str(row["source_record_id"]), "query_raw": row["query_raw"]}], args.model, "http://localhost:11434", 180)
            row["pilot_translation"] = response[0]["query_translated"].strip()
            row["pilot_flags"] = "|".join(quality_flags(row["query_raw"], row["pilot_translation"]))
            row["error"] = ""
        except Exception as exc:
            row["pilot_translation"] = ""
            row["pilot_flags"] = "CALL_FAILED"
            row["error"] = str(exc)
        row["runtime_seconds"] = round(time.perf_counter() - before, 3)
        rows.append(row)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows).to_csv(args.output, index=False, encoding="utf-8-sig")
        print({"processed": len(rows), "rows": len(sample)}, flush=True)
    report = {"model": args.model, "rows": len(rows), "calls": len(rows), "failed_calls": sum(bool(row["error"]) for row in rows), "flagged_rows": sum(bool(row["pilot_flags"]) for row in rows), "runtime_seconds": round(time.perf_counter() - started, 3), "accuracy": None}
    args.output.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
