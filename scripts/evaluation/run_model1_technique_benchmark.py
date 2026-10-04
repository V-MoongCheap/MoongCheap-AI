"""Benchmark Model 1 prompting and inference techniques on one fixed corpus."""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.request
from pathlib import Path
from typing import Any

import pandas as pd

from moongcheap_ai.data_foundation.model1 import ModelCallError, parse_model_output
from moongcheap_ai.data_foundation.model1_consensus import select_consensus


BASE_INSTRUCTION = """You are a facet-discovery assistant for a general e-commerce catalog.
Input is evidence only. Discover at most one consumer-useful facet and one observed value.
Do not infer attributes, prices, IDs, brands, seller names, category words, or intent.
Copy source_product_id and source_text exactly from the input. If evidence is insufficient,
return an empty facets array. Return JSON only:
{"category_key":"...","category_name":"...","facets":[{"facet_id_candidate":"semantic_key","name":"...","definition":"...","values":[{"value":"...","aliases":[]}],"evidence":[{"source_product_id":"...","source_field":"...","source_text":"..."}]}]}
"""

STRICT = BASE_INSTRUCTION + """
Every proposed value must be a literal substring of source_text or another supplied evidence field.
Use exactly one evidence item. Never use a normalized or translated evidence string.
"""

FEWSHOT = STRICT + """
Examples (use only when literally supported):
- Input evidence contains '스텐' -> facet_key 'material', value '스텐', copied evidence.
- Input contains only a brand or category name -> facets [].
Do not copy an example value unless the current input contains it.
"""


def _call_ollama(endpoint: str, model: str, prompt: str, temperature: float) -> dict[str, Any]:
    body = json.dumps({
        "model": model,
        "prompt": prompt,
        "format": "json",
        "stream": False,
        "think": False,
        "options": {"temperature": temperature, "num_predict": 256},
    }, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        endpoint.rstrip("/") + "/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=int(os.getenv("MODEL1_OLLAMA_TIMEOUT_SECONDS", "300")),
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise ModelCallError(str(exc)) from exc
    if not isinstance(payload, dict):
        raise ModelCallError("invalid Ollama response envelope")
    raw = payload.get("response", "")
    if not isinstance(raw, str):
        raise ModelCallError("invalid Ollama response text")
    if not raw:
        raise ModelCallError("empty Ollama response")
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ModelCallError("model output must be a JSON object")
        return parsed
    except json.JSONDecodeError as exc:
        raise ModelCallError("invalid JSON response") from exc


def _prompt(instruction: str, category: str, rows: list[dict[str, Any]]) -> str:
    return (
        instruction
        + f"\nTarget category_key: {category}\n"
        + "Input products/evidence:\n"
        + json.dumps(rows, ensure_ascii=False)
    )


def _retrieved(rows: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    """Keep the most informative evidence rows, deterministically."""
    ranked = sorted(
        rows,
        key=lambda row: (-len(str(row.get("evidence_text", ""))), str(row.get("source_product_id", ""))),
    )
    return ranked[:limit]


def _quality(parsed: pd.DataFrame, rows: list[dict[str, Any]]) -> dict[str, float | int]:
    if parsed.empty:
        return {"candidate_rows": 0, "valid_source_id_rate": 0.0, "evidence_copy_rate": 0.0, "value_evidence_rate": 0.0, "duplicate_rate": 0.0}
    by_id = {str(row.get("source_product_id", "")): row for row in rows}
    valid = 0
    copied = 0
    value_grounded = 0
    keys: list[tuple[str, str]] = []
    for row in parsed.to_dict("records"):
        source_id = str(row.get("source_product_id", ""))
        source_text = str(row.get("source_text", ""))
        value = str(row.get("value", ""))
        source = by_id.get(source_id)
        if source is not None:
            valid += 1
            evidence_blob = " ".join(str(value) for value in source.values())
            if source_text and source_text in evidence_blob:
                copied += 1
            if value and value.casefold() in evidence_blob.casefold():
                value_grounded += 1
        keys.append((str(row.get("name", "")).casefold(), value.casefold()))
    duplicate_count = len(keys) - len(set(keys))
    total = len(parsed)
    return {
        "candidate_rows": total,
        "valid_source_id_rate": round(valid / total, 4),
        "evidence_copy_rate": round(copied / total, 4),
        "value_evidence_rate": round(value_grounded / total, 4),
        "duplicate_rate": round(duplicate_count / total, 4),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model", default="qwen3:1.7b")
    parser.add_argument("--endpoint", default="http://localhost:11434")
    parser.add_argument("--max-categories", type=int, default=30)
    parser.add_argument("--consistency-attempts", type=int, default=3)
    args = parser.parse_args()
    if args.consistency_attempts < 1 or args.max_categories < 1:
        parser.error("consistency-attempts and max-categories must be positive")
    source = [json.loads(line) for line in args.input.read_text(encoding="utf-8").splitlines() if line.strip()]
    source = source[: args.max_categories]
    techniques = {
        "baseline": (BASE_INSTRUCTION, 0.0, False),
        "strict_grounding": (STRICT, 0.0, False),
        "few_shot_grounding": (FEWSHOT, 0.0, False),
        "evidence_retrieval": (STRICT, 0.0, True),
        "self_consistency": (STRICT, 0.2, False),
    }
    records: list[dict[str, Any]] = []
    raw_dir = args.output_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    for technique, (instruction, temperature, retrieve) in techniques.items():
        started = time.perf_counter()
        calls = 0
        failures = 0
        successes = 0
        quality_rows: list[dict[str, Any]] = []
        raw_rows: list[dict[str, Any]] = []
        for item in source:
            category = str(item.get("category_key", ""))
            rows = list(item.get("products", []))
            prompt_rows = _retrieved(rows) if retrieve else rows
            attempts = args.consistency_attempts if technique == "self_consistency" else 1
            parsed_attempts: list[pd.DataFrame] = []
            for attempt in range(attempts):
                calls += 1
                try:
                    payload = _call_ollama(args.endpoint, args.model, _prompt(instruction, category, prompt_rows), temperature)
                    raw_rows.append({"category_key": category, "attempt": attempt + 1, "payload": payload})
                    parsed, parse_failures = parse_model_output(payload, pd.DataFrame(prompt_rows))
                    if not parsed.empty:
                        parsed_attempts.append(parsed)
                    if parse_failures:
                        failures += len(parse_failures)
                except ModelCallError as exc:
                    failures += 1
                    raw_rows.append({"category_key": category, "attempt": attempt + 1, "error": str(exc)})
            if not parsed_attempts:
                continue
            if technique == "self_consistency":
                selected = select_consensus(parsed_attempts, attempts)
            else:
                selected = parsed_attempts[0]
            if selected.empty:
                continue
            successes += 1
            quality_rows.append({"category_key": category, **_quality(selected, prompt_rows)})
        summary_quality = pd.DataFrame(quality_rows)
        summary = {
            "technique": technique,
            "model": args.model,
            "categories": len(source),
            "successful_categories": successes,
            "success_rate": round(successes / max(len(source), 1), 4),
            "calls": calls,
            "failure_count": failures,
            "runtime_seconds": round(time.perf_counter() - started, 3),
            "candidate_rows": int(summary_quality.get("candidate_rows", pd.Series(dtype=int)).sum()),
            "valid_source_id_rate": round(float(summary_quality.get("valid_source_id_rate", pd.Series(dtype=float)).mean()) if not summary_quality.empty else 0.0, 4),
            "evidence_copy_rate": round(float(summary_quality.get("evidence_copy_rate", pd.Series(dtype=float)).mean()) if not summary_quality.empty else 0.0, 4),
            "value_evidence_rate": round(float(summary_quality.get("value_evidence_rate", pd.Series(dtype=float)).mean()) if not summary_quality.empty else 0.0, 4),
            "duplicate_rate": round(float(summary_quality.get("duplicate_rate", pd.Series(dtype=float)).mean()) if not summary_quality.empty else 0.0, 4),
        }
        records.append(summary)
        (raw_dir / f"{technique}.jsonl").write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in raw_rows) + "\n", encoding="utf-8")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report = {"model": args.model, "input": str(args.input), "techniques": records}
    (args.output_dir / "technique_benchmark_v1.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pd.DataFrame(records).to_csv(args.output_dir / "technique_benchmark_v1.csv", index=False, encoding="utf-8-sig")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
