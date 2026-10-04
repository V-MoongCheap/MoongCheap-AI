"""Benchmark combinations of Model 1 techniques with repeated runs."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd

from moongcheap_ai.data_foundation.model1 import ModelCallError, parse_model_output
from moongcheap_ai.data_foundation.model1_consensus import gate_observed_candidates, select_consensus
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.evaluation.run_model1_advanced_technique_benchmark import _summary
from scripts.evaluation.run_model1_technique_benchmark import (
    FEWSHOT,
    STRICT,
    _call_ollama,
    _quality,
)


def _call(endpoint: str, model: str, instruction: str, category: str, rows: list[dict[str, Any]], temperature: float) -> tuple[pd.DataFrame, str]:
    try:
        payload = _call_ollama(endpoint, model, f"{instruction}\nTarget category_key: {category}\nInput products/evidence:\n{json.dumps(rows, ensure_ascii=False)}", temperature)
        parsed, failures = parse_model_output(payload, pd.DataFrame(rows))
        return parsed, ";".join(item.get("failure_type", "failure") for item in failures)
    except ModelCallError as exc:
        return pd.DataFrame(), str(exc)


def _gate(frame: pd.DataFrame, rows: list[dict[str, Any]]) -> pd.DataFrame:
    return gate_observed_candidates(frame, rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model", default="qwen3:4b")
    parser.add_argument("--endpoint", default="http://localhost:11434")
    parser.add_argument("--max-categories", type=int, default=6)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument(
        "--combinations",
        default="fewshot_gate,fewshot_summary_gate,adaptive_gate,fewshot_consistency_gate,adaptive_support_gate,fewshot_summary_consistency_gate,fewshot_verifier_gate",
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    source = [json.loads(line) for line in args.input.read_text(encoding="utf-8").splitlines() if line.strip()][:args.max_categories]
    combinations = tuple(item.strip() for item in args.combinations.split(",") if item.strip())
    allowed = {"fewshot_gate", "fewshot_summary_gate", "adaptive_gate",
               "fewshot_consistency_gate", "adaptive_support_gate",
               "fewshot_summary_consistency_gate", "fewshot_verifier_gate"}
    if args.repeats < 1 or args.max_categories < 1 or not combinations or set(combinations) - allowed:
        parser.error("positive repeats/max-categories and known combinations are required")
    records: list[dict[str, Any]] = []
    for repeat in range(1, args.repeats + 1):
        for combination in combinations:
            started = time.perf_counter()
            calls = successes = failures = 0
            quality_rows: list[dict[str, Any]] = []
            for item in source:
                category = str(item.get("category_key", ""))
                rows = list(item.get("products", []))
                selected = pd.DataFrame()
                error = ""
                if combination == "fewshot_gate":
                    calls += 1
                    selected, error = _call(args.endpoint, args.model, FEWSHOT, category, rows, args.temperature)
                    selected = _gate(selected, rows)
                elif combination == "fewshot_summary_gate":
                    calls += 1
                    selected, error = _call(args.endpoint, args.model, FEWSHOT + "\n" + _summary(rows), category, rows, args.temperature)
                    selected = _gate(selected, rows)
                elif combination == "adaptive_gate":
                    calls += 1
                    selected, error = _call(args.endpoint, args.model, STRICT, category, rows, args.temperature)
                    selected = _gate(selected, rows)
                    if selected.empty:
                        calls += 1
                        selected, fallback_error = _call(args.endpoint, args.model, FEWSHOT + "\n" + _summary(rows), category, rows, args.temperature)
                        selected = _gate(selected, rows)
                        error = error or fallback_error
                elif combination == "adaptive_support_gate":
                    calls += 1
                    selected, error = _call(args.endpoint, args.model, STRICT, category, rows, args.temperature)
                    selected = _gate(selected, rows)
                    if selected.empty:
                        calls += 1
                        selected, fallback_error = _call(args.endpoint, args.model, FEWSHOT, category, rows, args.temperature)
                        selected = _gate(selected, rows)
                        error = error or fallback_error
                    # The second gate requires every accepted value to be
                    # directly present in evidence, not merely a valid parse.
                    selected = _gate(selected, rows)
                elif combination == "fewshot_summary_consistency_gate":
                    attempts: list[pd.DataFrame] = []
                    for _ in range(3):
                        calls += 1
                        draft, attempt_error = _call(args.endpoint, args.model, FEWSHOT + "\n" + _summary(rows), category, rows, args.temperature)
                        if not draft.empty:
                            attempts.append(_gate(draft, rows))
                        error = error or attempt_error
                    if attempts:
                        selected = select_consensus(attempts, 3)
                elif combination == "fewshot_verifier_gate":
                    calls += 1
                    draft, error = _call(args.endpoint, args.model, FEWSHOT, category, rows, args.temperature)
                    if not draft.empty:
                        verification_rows = rows + [{"source_product_id": "DRAFT_CANDIDATE", "evidence_text": draft.to_json(orient="records", force_ascii=False)}]
                        calls += 1
                        selected, verify_error = _call(
                            args.endpoint,
                            args.model,
                            STRICT + "\nReturn only candidates directly supported by the supplied evidence.",
                            category,
                            verification_rows,
                            args.temperature,
                        )
                        error = error or verify_error
                        selected = _gate(selected, rows)
                else:
                    attempts: list[pd.DataFrame] = []
                    for _ in range(3):
                        calls += 1
                        draft, attempt_error = _call(args.endpoint, args.model, FEWSHOT, category, rows, args.temperature)
                        if not draft.empty:
                            attempts.append(_gate(draft, rows))
                        error = error or attempt_error
                    if attempts:
                        selected = select_consensus(attempts, 3)
                failures += int(bool(error))
                if not selected.empty:
                    successes += 1
                    quality_rows.append({"category_key": category, **_quality(selected, rows)})
            quality = pd.DataFrame(quality_rows)
            records.append({
                "repeat": repeat,
                "combination": combination,
                "model": args.model,
                "categories": len(source),
                "successful_categories": successes,
                "success_rate": round(successes / max(len(source), 1), 4),
                "calls": calls,
                "failure_count": failures,
                "runtime_seconds": round(time.perf_counter() - started, 3),
                "value_evidence_rate": round(float(quality.get("value_evidence_rate", pd.Series(dtype=float)).mean()) if not quality.empty else 0.0, 4),
            })
            pd.DataFrame(records).to_csv(
                args.output_dir / "combination_benchmark_checkpoint_v1.csv",
                index=False,
                encoding="utf-8-sig",
            )
    result = pd.DataFrame(records)
    result.to_csv(args.output_dir / "combination_benchmark_v1.csv", index=False, encoding="utf-8-sig")
    report = {"model": args.model, "repeats": args.repeats, "results": records, "aggregate": result.groupby("combination", as_index=False).agg(success_rate_mean=("success_rate", "mean"), success_rate_min=("success_rate", "min"), value_evidence_rate_mean=("value_evidence_rate", "mean"), runtime_seconds_mean=("runtime_seconds", "mean"), calls_mean=("calls", "mean")).to_dict("records")}
    (args.output_dir / "combination_benchmark_v1.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
