from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import pandas as pd

from moongcheap_ai.model1 import ModelCallError, UnavailableModelAdapter, discover_model_config, sample_products


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Model 1 Facet Discovery smoke/blocked pipeline")
    parser.add_argument("--input", type=Path, default=Path("data/interim/facet_discovery/i0030_products_clean_dedup.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed/model1_v0"))
    parser.add_argument("--max-per-category", type=int, default=24)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    frame = pd.read_csv(args.input, dtype=str).fillna("")
    sampled = sample_products(frame, max_per_category=args.max_per_category)
    sampled.to_csv(args.output_dir / "facet_discovery_model_input_v0.csv", index=False, encoding="utf-8-sig")
    config = discover_model_config()
    started = time.perf_counter()
    report = {"status": "BLOCKED_NO_EXECUTABLE_MODEL", "provider": config.provider if config else None, "model": config.model if config else None, "prompt_version": "facet_discovery_v0", "sampling_seed": 42, "category_sample_counts": sampled.groupby("category_key").size().to_dict() if not sampled.empty else {}, "model_call_count": 0, "input_token": None, "output_token": None, "runtime_seconds": round(time.perf_counter() - started, 3), "api_cost": None, "blocker": "No MODEL1_PROVIDER/MODEL1_MODEL configuration, no executable local model detected; no fake model output was created."}
    try:
        UnavailableModelAdapter().generate_facet_candidates("", [], "facet_discovery_v0")
    except ModelCallError as exc:
        report["failure_type"] = "MODEL_CALL_FAILED"
        report["failure_detail"] = str(exc)
    (args.output_dir / "facet_discovery_model_raw_v0.jsonl").write_text("", encoding="utf-8")
    pd.DataFrame(columns=["failure_type", "category_key", "detail"]).to_csv(args.output_dir / "facet_discovery_failures_v0.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(columns=["category_name", "normalized_facet_candidate", "comparison_status", "rule_support", "model_support", "rule_evidence", "model_evidence"]).to_csv(args.output_dir / "facet_discovery_comparison_v0.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(columns=["category_key", "category_name", "facet_id_candidate", "name", "definition", "value", "alias", "source_product_id", "source_field", "source_text", "status"]).to_csv(args.output_dir / "facet_discovery_model_review_v0.csv", index=False, encoding="utf-8-sig")
    (args.output_dir / "facet_discovery_model_merged_v0.json").write_text(json.dumps({"status": "BLOCKED_NO_EXECUTABLE_MODEL", "categories": []}, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.output_dir / "facet_discovery_model_report_v0.md").write_text("# Model 1 Facet Discovery V0\n\n- Status: BLOCKED_NO_EXECUTABLE_MODEL\n- Sampling input was generated from the actual MFDS Product Corpus and V2.1 Category mapping.\n- No fake Model output was generated.\n- Configure `MODEL1_PROVIDER` and `MODEL1_MODEL`, or install/configure an executable local model, then rerun this script.\n", encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
