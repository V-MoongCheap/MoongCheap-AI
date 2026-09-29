"""Benchmark additional Model 1 improvement techniques on a fixed corpus."""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

from moongcheap_ai.data_foundation.model1 import ModelCallError, parse_model_output

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.evaluation.run_model1_technique_benchmark import (
    FEWSHOT,
    STRICT,
    _call_ollama,
    _prompt,
    _quality,
)


def _summary(rows: list[dict[str, Any]]) -> str:
    values: Counter[str] = Counter()
    for row in rows:
        for field in ("product_form", "functional_ingredients", "evidence_text"):
            value = str(row.get(field, "")).strip()
            if value:
                values[value] += 1
    return "Observed evidence frequency summary (not generated facts):\n" + "\n".join(
        f"- {value}: {count}" for value, count in values.most_common(20)
    )


def _keys(frame: pd.DataFrame) -> set[tuple[str, str]]:
    return {(str(row.get("name", "")).casefold(), str(row.get("value", "")).casefold()) for row in frame.to_dict("records")}


def _call(endpoint: str, model: str, instruction: str, category: str, rows: list[dict[str, Any]], temperature: float = 0.0) -> tuple[pd.DataFrame, str]:
    try:
        payload = _call_ollama(endpoint, model, _prompt(instruction, category, rows), temperature)
        parsed, failures = parse_model_output(payload, pd.DataFrame(rows))
        return parsed, "" if not failures else ";".join(item.get("failure_type", "failure") for item in failures)
    except ModelCallError as exc:
        return pd.DataFrame(), str(exc)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model", default="qwen3:4b")
    parser.add_argument("--endpoint", default="http://localhost:11434")
    parser.add_argument("--max-categories", type=int, default=6)
    parser.add_argument(
        "--techniques",
        default="adaptive_fallback,prompt_ensemble,category_summary,two_stage_verifier,evidence_support_gate",
    )
    args = parser.parse_args()
    source = [json.loads(line) for line in args.input.read_text(encoding="utf-8").splitlines() if line.strip()][:args.max_categories]
    techniques = tuple(item.strip() for item in args.techniques.split(",") if item.strip())
    results: list[dict[str, Any]] = []
    for technique in techniques:
        started = time.perf_counter()
        calls = 0
        successes = 0
        failures = 0
        accepted: list[pd.DataFrame] = []
        for item in source:
            category = str(item.get("category_key", ""))
            rows = list(item.get("products", []))
            selected = pd.DataFrame()
            if technique == "adaptive_fallback":
                calls += 1
                selected, error = _call(args.endpoint, args.model, STRICT, category, rows)
                if selected.empty:
                    calls += 1
                    selected, error = _call(args.endpoint, args.model, FEWSHOT, category, rows)
                failures += int(bool(error))
            elif technique == "prompt_ensemble":
                calls += 2
                first, error_a = _call(args.endpoint, args.model, STRICT, category, rows)
                second, error_b = _call(args.endpoint, args.model, FEWSHOT, category, rows)
                common = _keys(first) & _keys(second)
                selected = first[first.apply(lambda row: (str(row.get("name", "")).casefold(), str(row.get("value", "")).casefold()) in common, axis=1)]
                failures += int(bool(error_a)) + int(bool(error_b))
            elif technique == "category_summary":
                calls += 1
                selected, error = _call(args.endpoint, args.model, FEWSHOT + "\n" + _summary(rows), category, rows)
                failures += int(bool(error))
            elif technique == "two_stage_verifier":
                calls += 1
                draft, error = _call(args.endpoint, args.model, FEWSHOT, category, rows)
                if not draft.empty:
                    verification_instruction = STRICT + "\nReturn a candidate only if it is directly supported by the evidence."
                    verification_rows = rows + [{"source_product_id": "DRAFT_CANDIDATE", "evidence_text": draft.to_json(orient="records", force_ascii=False)}]
                    calls += 1
                    selected, verify_error = _call(args.endpoint, args.model, verification_instruction, category, verification_rows)
                    error = error or verify_error
                failures += int(bool(error))
            else:
                calls += 1
                draft, error = _call(args.endpoint, args.model, FEWSHOT, category, rows)
                if not draft.empty:
                    evidence_blob = " ".join(str(value) for row in rows for value in row.values()).casefold()
                    selected = draft[draft["value"].astype(str).map(lambda value: bool(value) and value.casefold() in evidence_blob)]
                failures += int(bool(error))
            if not selected.empty:
                successes += 1
                accepted.append(selected)
        frame = pd.concat(accepted, ignore_index=True) if accepted else pd.DataFrame()
        quality = _quality(frame, [row for item in source for row in item.get("products", [])])
        results.append({
            "technique": technique,
            "model": args.model,
            "categories": len(source),
            "successful_categories": successes,
            "success_rate": round(successes / max(len(source), 1), 4),
            "calls": calls,
            "failure_count": failures,
            "runtime_seconds": round(time.perf_counter() - started, 3),
            **quality,
        })
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report = {"model": args.model, "input": str(args.input), "techniques": results}
    (args.output_dir / "advanced_technique_benchmark_v1.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pd.DataFrame(results).to_csv(args.output_dir / "advanced_technique_benchmark_v1.csv", index=False, encoding="utf-8-sig")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
