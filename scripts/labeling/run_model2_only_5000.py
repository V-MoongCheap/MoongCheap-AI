"""Run Model 2 without Rule fallback over the complete grounded Demand set."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from moongcheap_ai.data_foundation.demand_label_comparison import LLMLabelingError, OllamaDemandLabeler, _apply_model_result
from moongcheap_ai.data_foundation.labeling import build_product_facet_map, load_taxonomy


def _write(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def _classify_with_retries(labeler, payload: list[dict[str, object]], loader, retry_batch_size: int) -> tuple[dict[str, dict[str, object]], dict[str, str]]:
    """Retry malformed or incomplete responses with smaller, bounded batches."""
    values: dict[str, dict[str, object]] = {}
    errors: dict[str, str] = {}
    queue = [payload]
    while queue:
        chunk = queue.pop(0)
        try:
            response = labeler.classify(chunk, loader)
        except LLMLabelingError as exc:
            if len(chunk) > retry_batch_size:
                midpoint = max(retry_batch_size, len(chunk) // 2)
                queue[0:0] = [chunk[:midpoint], chunk[midpoint:]]
            else:
                for item in chunk:
                    errors[str(item["demand_id"])] = str(exc)
            continue
        values.update(response)
        missing = [item for item in chunk if str(item["demand_id"]) not in response]
        if missing:
            if len(missing) > retry_batch_size:
                for start in range(0, len(missing), retry_batch_size):
                    queue.append(missing[start:start + retry_batch_size])
            else:
                for item in missing:
                    errors[str(item["demand_id"])] = "model response omitted demand_id"
    return values, errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Model 2 only over grounded Demand rows")
    parser.add_argument("--input", type=Path, default=Path("data/processed/demand_5000_v1/grounded_demand_5000_raw.csv"))
    parser.add_argument("--taxonomy", type=Path, default=Path("data/processed/downstream_v2_1/taxonomy_candidate_v2_1.json"))
    parser.add_argument("--product-facets", type=Path, default=Path("data/processed/model1_v0_refresh4/product_facet_mapping_v0.csv"))
    parser.add_argument("--output", type=Path, default=Path("data/processed/demand_5000_v1/model2_only_labeled_5000_v1.csv"))
    parser.add_argument("--model", default=None)
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--retry-batch-size", type=int, default=10)
    parser.add_argument("--group-by-category", action="store_true", help="Send each model batch from one Category only")
    parser.add_argument("--request-timeout", type=int, default=300, help="Ollama request timeout in seconds")
    parser.add_argument("--execution-meta", type=Path, default=None, help="Path for this run's execution metadata JSON")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    model = args.model or os.environ.get("MODEL2_MODEL", "") or os.environ.get("MODEL1_MODEL", "")
    if not model:
        raise SystemExit("set --model or MODEL2_MODEL")
    demands = pd.read_csv(args.input, dtype=str).fillna("")
    loader = load_taxonomy(args.taxonomy)
    facet_frame = pd.read_csv(args.product_facets, dtype=str).fillna("")
    used = set(demands["product_reference"].astype(str)) if "product_reference" in demands else set()
    facets = build_product_facet_map(facet_frame[facet_frame["source_product_id"].astype(str).isin(used)])
    labeler = OllamaDemandLabeler(model, timeout=args.request_timeout)
    completed: dict[str, dict[str, object]] = {}
    if args.resume and args.output.exists():
        previous = pd.read_csv(args.output, dtype=str).fillna("")
        completed = {str(row["demand_id"]): row.to_dict() for _, row in previous.iterrows()}
    started = time.perf_counter()
    model_failures = 0
    rows = []
    if args.group_by_category:
        batches = [group.iloc[start:start + args.batch_size] for _, group in demands.groupby("category_id", sort=True) for start in range(0, len(group), args.batch_size)]
    else:
        batches = [demands.iloc[start:start + args.batch_size] for start in range(0, len(demands), args.batch_size)]
    for batch_number, batch in enumerate(batches, 1):
        if completed and all(str(demand_id) in completed and str(completed[str(demand_id)].get("model_status", "")).startswith("LABELED") for demand_id in batch["demand_id"]):
            rows.extend(completed[str(demand_id)] for demand_id in batch["demand_id"])
            print({"completed_batches": batch_number, "total_batches": len(batches), "model_calls": labeler.call_count, "resumed": True}, flush=True)
            continue
        payload = []
        for _, row in batch.iterrows():
            defaults, _ = loader.product_defaults(row["category_id"], facets.get(str(row["catalog_id"]), []))
            payload.append({"demand_id": row["demand_id"], "category_id": row["category_id"], "extra_requirement": row["extra_requirement"], "product_defaults": defaults})
        model_values, model_errors = _classify_with_retries(labeler, payload, loader, args.retry_batch_size)
        for _, source in batch.iterrows():
            demand_id = str(source["demand_id"])
            previous = completed.get(demand_id)
            previous_is_success = previous and str(previous.get("model_status", "")).startswith("LABELED")
            if demand_id in model_values:
                values, warnings = _apply_model_result(source, model_values[demand_id], loader, facets.get(str(source["catalog_id"]), []))
                row = source.to_dict()
                row.update({"model_label": loader.encode(values), "model_status": "LABELED" if not warnings else "LABELED_WITH_REVIEW", "model_warnings": json.dumps(warnings, ensure_ascii=False), "model_facet_values": json.dumps(values, ensure_ascii=False, separators=(",", ":"))})
            elif previous_is_success:
                rows.append(previous)
                continue
            else:
                row = source.to_dict()
                warning = model_errors.get(demand_id, "missing LLM result")
                row.update({"model_label": "", "model_status": "MODEL_FAILURE", "model_warnings": json.dumps([warning], ensure_ascii=False), "model_facet_values": ""})
                model_failures += 1
            rows.append(row)
        _write(pd.DataFrame(rows), args.output)
        print({"completed_batches": batch_number, "total_batches": len(batches), "model_calls": labeler.call_count}, flush=True)
    result = pd.DataFrame(rows)
    _write(result, args.output)
    meta = {"provider": "ollama", "model": model, "rows": len(result), "model_calls": labeler.call_count, "model_failures": model_failures, "runtime_seconds": round(time.perf_counter() - started, 3), "batch_size": args.batch_size, "group_by_category": args.group_by_category}
    meta_path = args.execution_meta or args.output.with_name("model2_only_execution_v1.json")
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print({"status": "COMPLETED", **meta})


if __name__ == "__main__":
    main()
