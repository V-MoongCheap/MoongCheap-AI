"""Compare Ollama Model 1 candidates on the expanded Domeggook corpus."""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter
from math import ceil
import time
from html import unescape
from pathlib import Path

import pandas as pd

from moongcheap_ai.data_foundation.model1 import OllamaAdapter, ModelCallError, parse_model_output


def _clean_text(value: object) -> str:
    text = unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _valid_general_candidate(row: dict) -> bool:
    value = _clean_text(row.get("value"))
    source_text = _clean_text(row.get("source_text"))
    if not value or not source_text:
        return False
    # Pure measurements and IDs are evidence, but not useful semantic values
    # for a first-pass general taxonomy.
    if re.fullmatch(r"[0-9]+(?:[./xX×-][0-9]+)*[a-zA-Z가-힣]*", value):
        return False
    if re.search(r"https?://|<img|<p\b", source_text, re.IGNORECASE):
        return False
    return True


def _apply_value_evidence_gate(
    candidates: pd.DataFrame, rows: list[dict]
) -> pd.DataFrame:
    """Reject values that do not literally occur in the category input."""
    if candidates.empty:
        return candidates
    evidence_blob = " ".join(
        str(value)
        for row in rows
        for key, value in row.items()
        if key not in {"source_product_id", "source_type"} and str(value).strip()
    ).casefold()
    return candidates[
        candidates["value"].astype(str).map(
            lambda value: bool(value.strip()) and value.casefold() in evidence_blob
        )
    ].copy()


def make_rows(frame: pd.DataFrame, min_category_products: int, max_per_category: int) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {}
    for category, group in frame.groupby("category_path", sort=True):
        if len(group) < min_category_products:
            continue
        group = group.sort_values("source_product_id").head(max_per_category)
        rows = []
        for item in group.to_dict(orient="records"):
            rows.append({
                "source_product_id": item.get("source_product_id", ""),
                "source_type": "DOMEGGOOK_API_PRODUCT",
                # Measurements, model IDs and legal boilerplate are excluded
                # from the Model 1 evidence prompt. They are retained in the
                # raw source and audit artifacts, but are not facet evidence.
                "product_form": "",
                "functional_ingredients": "",
                "intake_method": "",
                "evidence_text": " | ".join(
                    f"{label}={value}"
                    for label, value in (
                        ("상품명", item.get("name", "")),
                        ("카테고리", item.get("category_path", "")),
                        ("상품설명", _clean_text(item.get("description_item", ""))),
                        ("제조사", item.get("manufacturer", "")),
                    )
                    if str(value).strip()
                )[:120],
                "consumer_search_text": "",
            })
        result[f"domeggook:{category}"] = rows
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--models", default="qwen3:1.7b,qwen2.5:3b,gemma3:1b,exaone3.5:2.4b")
    parser.add_argument("--min-category-products", type=int, default=10)
    parser.add_argument("--max-per-category", type=int, default=12)
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument(
        "--consistency-attempts",
        type=int,
        default=1,
        help="Independent generations per category; keep candidates receiving majority votes.",
    )
    parser.add_argument(
        "--consistency-temperature",
        type=float,
        default=0.2,
        help="Temperature used when consistency-attempts is greater than one.",
    )
    parser.add_argument("--prompt", type=Path, default=Path("prompts/facet_discovery_general_v1_few_shot.txt"))
    args = parser.parse_args()
    # Use the versioned Few-shot prompt by default.  Small-context compact mode
    # remains available explicitly via MODEL1_COMPACT_PROMPT=true.
    os.environ.setdefault("MODEL1_COMPACT_PROMPT", "false")
    os.environ.setdefault("MODEL1_CATEGORY_SUMMARY", "true")
    os.environ.setdefault("MODEL1_MAX_NEW_TOKENS", "256")
    frame = pd.read_csv(args.input, dtype=str).fillna("")
    groups = make_rows(frame, args.min_category_products, args.max_per_category)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "model_input_v1.jsonl").write_text(
        "\n".join(json.dumps({"category_key": key, "products": rows}, ensure_ascii=False) for key, rows in groups.items()) + "\n",
        encoding="utf-8",
    )
    all_raw: list[dict] = []
    all_candidates: list[dict] = []
    all_failures: list[dict] = []
    reports: list[dict] = []
    for model in [x.strip() for x in args.models.split(",") if x.strip()]:
        adapter = OllamaAdapter(model, prompt_path=args.prompt)
        started = time.perf_counter()
        calls = 0
        candidates = 0
        failures = 0
        successful = 0
        for category_key, rows in groups.items():
            best = pd.DataFrame()
            category_failures: list[dict] = []
            attempt_count = max(args.retries + 1, args.consistency_attempts)
            parsed_attempts: list[pd.DataFrame] = []
            for attempt in range(attempt_count):
                calls += 1
                os.environ["MODEL1_TEMPERATURE"] = str(
                    args.consistency_temperature if args.consistency_attempts > 1 else 0
                )
                try:
                    payload = adapter.generate_facet_candidates(category_key, rows, "domeggook_facet_comparison_v1")
                    all_raw.append({"model": model, "category_key": category_key, "attempt": attempt + 1, "response": payload})
                    parsed, parse_failures = parse_model_output(payload, pd.DataFrame(rows))
                    parsed = parsed[
                        parsed.apply(lambda item: _valid_general_candidate(item.to_dict()), axis=1)
                    ].copy()
                    parsed = _apply_value_evidence_gate(parsed, rows)
                    parsed_attempts.append(parsed)
                    category_failures = parse_failures
                except ModelCallError as exc:
                    category_failures = [{"failure_type": "MODEL_CALL_FAILED", "detail": str(exc)}]
            if parsed_attempts:
                required_votes = ceil(args.consistency_attempts / 2) if args.consistency_attempts > 1 else 1
                votes = Counter(
                    (
                        str(row.get("name", "")).casefold().strip(),
                        str(row.get("value", "")).casefold().strip(),
                    )
                    for parsed in parsed_attempts
                    for row in parsed.to_dict(orient="records")
                )
                accepted_keys = {key for key, count in votes.items() if count >= required_votes}
                for parsed in parsed_attempts:
                    if not parsed.empty:
                        keys = [
                            (str(row.get("name", "")).casefold().strip(), str(row.get("value", "")).casefold().strip())
                            for row in parsed.to_dict(orient="records")
                        ]
                        candidate = parsed.loc[[key in accepted_keys for key in keys]]
                        if not candidate.empty:
                            best = candidate
                            break
            if not best.empty:
                successful += 1
                candidates += len(best)
                all_candidates.extend([{**row, "model": model} for row in best.to_dict(orient="records")])
            if category_failures:
                failures += len(category_failures)
                all_failures.extend([{**row, "model": model, "category_key": category_key} for row in category_failures])
        reports.append({"model": model, "calls": calls, "categories": len(groups), "successful_categories": successful, "candidate_rows": candidates, "failure_rows": failures, "runtime_seconds": round(time.perf_counter() - started, 3), "consistency_attempts": args.consistency_attempts, "consistency_required_votes": ceil(args.consistency_attempts / 2) if args.consistency_attempts > 1 else 1})
    pd.DataFrame(all_candidates).to_csv(args.output_dir / "model_candidates_v1.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(all_failures).to_csv(args.output_dir / "model_failures_v1.csv", index=False, encoding="utf-8-sig")
    (args.output_dir / "model_raw_responses_v1.jsonl").write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in all_raw) + "\n", encoding="utf-8")
    (args.output_dir / "comparison_report_v1.json").write_text(json.dumps({"input_rows": len(frame), "eligible_categories": len(groups), "models": reports}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"input_rows": len(frame), "eligible_categories": len(groups), "models": reports}, ensure_ascii=False))


if __name__ == "__main__":
    main()
