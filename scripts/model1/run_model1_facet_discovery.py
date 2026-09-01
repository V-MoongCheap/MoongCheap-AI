from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import pandas as pd

from moongcheap_ai.model1 import ModelCallError, OllamaAdapter, UnavailableModelAdapter, discover_model_config, parse_model_output, sample_products


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Model 1 Facet Discovery smoke/blocked pipeline")
    parser.add_argument("--input", type=Path, default=Path("data/interim/facet_discovery/i0030_products_clean_dedup.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed/model1_v0"))
    parser.add_argument("--max-per-category", type=int, default=24)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--smoke-only", action="store_true")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    frame = pd.read_csv(args.input, dtype=str).fillna("")
    sampled = sample_products(frame, max_per_category=args.max_per_category)
    sampled.to_csv(args.output_dir / "facet_discovery_model_input_v0.csv", index=False, encoding="utf-8-sig")
    config = discover_model_config()
    started = time.perf_counter()
    target_categories = {"health-functional-food:vitamin_mineral", "health-functional-food:probiotics", "health-functional-food:skin_collagen"} if args.smoke_only else set(sampled["category_key"].unique())
    model = OllamaAdapter(config.model) if config and config.provider.casefold() == "ollama" else UnavailableModelAdapter()
    raw_path = args.output_dir / "facet_discovery_model_raw_v0.jsonl"
    review_rows, failures, merged = [], [], []
    calls = 0
    with raw_path.open("w", encoding="utf-8") as raw_file:
        for category_key, group in sampled[sampled["category_key"].isin(target_categories)].groupby("category_key", sort=True):
            category_failures = []
            best_parsed = pd.DataFrame()
            for attempt in range(args.max_retries + 1):
                try:
                    response = model.generate_facet_candidates(category_key, group.to_dict("records"), "facet_discovery_v0")
                    calls += 1
                    raw_file.write(json.dumps({"category_key": category_key, "attempt": attempt + 1, "response": response}, ensure_ascii=False) + "\n")
                    parsed, parse_failures = parse_model_output(response, group)
                    if not parsed.empty:
                        best_parsed = parsed
                    if not parse_failures or not parsed.empty:
                        review_rows.extend(best_parsed.to_dict("records"))
                        merged.append(response)
                        category_failures = parse_failures
                        break
                    category_failures = parse_failures
                except ModelCallError as exc:
                    category_failures = [{"failure_type": "MODEL_CALL_FAILED", "detail": str(exc)}]
            failures.extend({"failure_type": failure["failure_type"], "category_key": category_key, "detail": failure["detail"]} for failure in category_failures)
    status = "COMPLETED" if calls == len(target_categories) and not failures else "COMPLETED_WITH_WARNINGS" if calls else "BLOCKED_NO_EXECUTABLE_MODEL"
    report = {"status": status, "provider": getattr(model, "provider", None), "model": getattr(model, "model", None), "prompt_version": "facet_discovery_v0", "sampling_seed": 42, "category_sample_counts": sampled[sampled["category_key"].isin(target_categories)].groupby("category_key").size().to_dict() if not sampled.empty else {}, "category_count": len(target_categories), "model_call_count": calls, "input_token": None, "output_token": None, "runtime_seconds": round(time.perf_counter() - started, 3), "api_cost": 0 if calls and getattr(model, "provider", "") == "ollama" else None, "failure_count": len(failures)}
    if not calls:
        report["blocker"] = "No MODEL1_PROVIDER/MODEL1_MODEL configuration, no executable local model detected; no fake model output was created."
    pd.DataFrame(failures, columns=["failure_type", "category_key", "detail"]).to_csv(args.output_dir / "facet_discovery_failures_v0.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(review_rows, columns=["category_key", "category_name", "facet_id_candidate", "name", "definition", "value", "alias", "source_product_id", "source_field", "source_text", "status"]).to_csv(args.output_dir / "facet_discovery_model_review_v0.csv", index=False, encoding="utf-8-sig")
    (args.output_dir / "facet_discovery_model_merged_v0.json").write_text(json.dumps({"status": status, "categories": merged}, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(columns=["category_name", "normalized_facet_candidate", "comparison_status", "rule_support", "model_support", "rule_evidence", "model_evidence"]).to_csv(args.output_dir / "facet_discovery_comparison_v0.csv", index=False, encoding="utf-8-sig")
    (args.output_dir / "facet_discovery_model_report_v0.md").write_text(f"# Model 1 Facet Discovery V0\n\n- Status: {status}\n- Provider: {report['provider']}\n- Model: {report['model']}\n- Category calls: {calls}/{len(target_categories)}\n- Input samples: {sum(report['category_sample_counts'].values())}\n- Token usage: null when provider does not report it\n- API cost: {report['api_cost']}\n- No Model 1 output is treated as final taxonomy.\n" + ("- Blocker: install/configure Ollama and set `MODEL1_PROVIDER=ollama`, `MODEL1_MODEL=<ollama list result>`.\n" if not calls else ""), encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
