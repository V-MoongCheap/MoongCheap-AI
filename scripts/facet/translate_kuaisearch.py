"""Translate KuaiSearch health queries for downstream Korean Facet extraction.

Raw Chinese query text is never overwritten. The translated layer is a
derived, local-only artifact and must not be treated as ground truth.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path

import pandas as pd


def _translate_batch(rows: list[dict[str, str]], model: str, endpoint: str, timeout: int) -> list[dict[str, str]]:
    prompt = (
        "Translate each Chinese ecommerce health-product query into natural Korean. "
        "Preserve product attributes and constraints; do not explain. Return JSON only "
        "as {\"translations\":[{\"source_record_id\":\"...\",\"query_translated\":\"...\"}]} "
        f"for every input row. Input: {json.dumps(rows, ensure_ascii=False)}"
    )
    body = json.dumps({"model": model, "prompt": prompt, "format": {"type": "object", "properties": {"translations": {"type": "array", "items": {"type": "object", "properties": {"source_record_id": {"type": "string"}, "query_translated": {"type": "string"}}, "required": ["source_record_id", "query_translated"]}}}, "required": ["translations"]}, "options": {"temperature": 0}, "stream": False, "think": False}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(f"{endpoint.rstrip('/')}/api/generate", data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    result = json.loads(payload.get("response", "{}"))
    return result.get("translations", []) if isinstance(result, dict) else []


def main() -> None:
    parser = argparse.ArgumentParser(description="Translate local KuaiSearch health queries into Korean")
    parser.add_argument("--input", type=Path, default=Path("data/interim/facet_evidence/kuaiseach_health_queries.parquet"))
    parser.add_argument("--output", type=Path, default=Path("data/interim/facet_evidence/kuaiseach_health_queries_ko.parquet"))
    parser.add_argument("--model", default="qwen3:4b")
    parser.add_argument("--endpoint", default="http://localhost:11434")
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()
    frame = pd.read_parquet(args.input).fillna("")
    frame = frame.drop_duplicates(subset=["query_raw"]).reset_index(drop=True)
    if args.limit is not None:
        frame = frame.iloc[:args.limit].copy()
    previous = pd.read_parquet(args.output).fillna("") if args.output.exists() else pd.DataFrame()
    cache = dict(zip(previous.get("query_raw", []), previous.get("query_translated", []))) if not previous.empty else {}
    frame["query_translated"] = frame["query_raw"].map(cache).fillna("")
    started = time.perf_counter(); calls = 0; failures = 0
    for start in range(0, len(frame), args.batch_size):
        batch = frame.iloc[start:start + args.batch_size]
        pending = batch[batch["query_translated"].eq("")]
        if not pending.empty:
            try:
                translated = _translate_batch([{"source_record_id": str(row.source_record_id), "query_raw": str(row.query_raw)} for row in pending.itertuples()], args.model, args.endpoint, args.timeout)
                lookup = {str(item.get("source_record_id")): str(item.get("query_translated", "")).strip() for item in translated if item.get("query_translated")}
                for index, row in pending.iterrows():
                    if str(row.source_record_id) in lookup:
                        frame.at[index, "query_translated"] = lookup[str(row.source_record_id)]
                calls += 1
            except Exception as exc:
                failures += 1
                print({"batch_start": start, "error": str(exc)}, flush=True)
        frame.to_parquet(args.output, index=False)
        print({"completed": min(start + args.batch_size, len(frame)), "rows": len(frame), "calls": calls, "failures": failures}, flush=True)
    frame.to_parquet(args.output, index=False)
    frame.to_csv(args.output.with_name(args.output.stem + "_preview.csv"), index=False, encoding="utf-8-sig")
    print({"status": "COMPLETED", "rows": len(frame), "translated": int(frame.query_translated.ne("").sum()), "calls": calls, "failures": failures, "runtime_seconds": round(time.perf_counter() - started, 3), "model": args.model})


if __name__ == "__main__":
    main()
