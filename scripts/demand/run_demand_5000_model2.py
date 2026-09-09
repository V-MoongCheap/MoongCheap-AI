"""Generate the 5,000-row grounded demand set and run Model 2 when available."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from moongcheap_ai.data_foundation.demand_5000 import generate_demand_5000, load_taxonomy, quality_markdown, quality_report
from moongcheap_ai.data_foundation.demand_label_comparison import LLMLabelingError, OllamaDemandLabeler, compare_labeling_methods
from moongcheap_ai.data_foundation.labeling import build_product_facet_map, label_demands, load_taxonomy as load_json_taxonomy


def _sample(frame: pd.DataFrame, count: int, seed: int) -> pd.DataFrame:
    if len(frame) <= count:
        return frame.copy()
    groups = frame.groupby(["category_id", "scenario_type"], sort=True, group_keys=False)
    selected = groups.head(1)
    remaining = frame.drop(selected.index).sample(frac=1, random_state=seed)
    return pd.concat([selected, remaining]).head(count).reset_index(drop=True)


def _write(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def _model_name(explicit: str | None) -> str:
    return explicit or os.environ.get("MODEL2_MODEL", "") or os.environ.get("MODEL1_MODEL", "")


def _empty_model_frame(sample: pd.DataFrame, reason: str) -> pd.DataFrame:
    result = sample[["demand_id", "catalog_id", "category_id"]].copy()
    result["model_label"] = ""
    result["model_status"] = "BLOCKED_NO_EXECUTABLE_MODEL"
    result["model_warnings"] = json.dumps([reason], ensure_ascii=False)
    return result


def _build_hybrid(rule: pd.DataFrame, sample_or_review: pd.DataFrame, llm_result: pd.DataFrame | None, max_llm_calls: int, model_available: bool) -> pd.DataFrame:
    result = rule.copy()
    result["interpretation_method"] = "RULE_ALIAS"
    result["hybrid_label"] = result["label"]
    result["hybrid_status"] = result["label_status"]
    result["hybrid_model_status"] = "NOT_RUN_RULE_SUCCESS"
    if not model_available:
        result.loc[result["label_status"] != "LABELED", "hybrid_model_status"] = "BLOCKED_NO_EXECUTABLE_MODEL"
        return result
    if llm_result is None or llm_result.empty:
        return result
    lookup = llm_result.set_index("demand_id")
    for index, row in result.iterrows():
        demand_id = str(row["demand_id"])
        if demand_id not in lookup.index:
            if row["label_status"] != "LABELED":
                result.at[index, "hybrid_model_status"] = "LLM_NOT_RUN_LIMIT"
            continue
        model_row = lookup.loc[demand_id]
        status = str(model_row.get("model_status", "MODEL_FAILURE"))
        if status == "MODEL_FAILURE":
            result.at[index, "hybrid_model_status"] = "MODEL_FAILURE"
            continue
        result.at[index, "hybrid_label"] = model_row.get("model_label", row["label"])
        result.at[index, "hybrid_status"] = model_row.get("model_status", "LABELED_WITH_REVIEW")
        result.at[index, "interpretation_method"] = "HYBRID_RULE_LLM"
        result.at[index, "hybrid_model_status"] = "LLM_ASSISTED"
    return result


def _model_result(sample: pd.DataFrame, taxonomy_path: Path, facets_path: Path, model: str, batch_size: int) -> tuple[pd.DataFrame, dict[str, object]]:
    taxonomy = load_json_taxonomy(taxonomy_path)
    facets = build_product_facet_map(pd.read_csv(facets_path, dtype=str).fillna(""))
    labeler = OllamaDemandLabeler(model)
    try:
        compared, summary = compare_labeling_methods(sample, taxonomy, facets, labeler, batch_size)
    except LLMLabelingError as exc:
        return _empty_model_frame(sample, str(exc)), {"status": "MODEL_FAILURE", "error": str(exc), "call_count": labeler.call_count, "runtime_seconds": labeler.runtime_seconds}
    output = compared[["demand_id", "catalog_id", "category_id", "model_label", "model_status", "model_warnings"]].copy()
    return output, {"status": "COMPLETED", "call_count": labeler.call_count, "runtime_seconds": labeler.runtime_seconds, "summary": summary.to_dict("records")}


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate and label 5,000 grounded consumer demands")
    parser.add_argument("--products", type=Path, default=Path("data/interim/facet_discovery/i0030_products_clean_dedup.csv"))
    parser.add_argument("--mapping", type=Path, default=Path("data/processed/category_v2_1_current3/product_service_category_mapping_v2_1.csv"))
    parser.add_argument("--taxonomy", type=Path, default=Path("data/processed/downstream_v2_1/taxonomy_candidate_v2_1.json"))
    parser.add_argument("--product-facets", type=Path, default=Path("data/processed/model1_v0_refresh4/product_facet_mapping_v0.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed/demand_5000_v1"))
    parser.add_argument("--count", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--model", default=None)
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--max-llm-calls", type=int, default=100)
    parser.add_argument("--reuse-llm-sample", action="store_true", help="Reuse an existing 200-row Model 2 result")
    args = parser.parse_args()
    started = time.perf_counter()
    required = [args.products, args.mapping, args.taxonomy, args.product_facets]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise SystemExit("missing local input: " + ", ".join(missing))

    demands = generate_demand_5000(args.products, args.mapping, args.taxonomy, args.product_facets, args.count, args.seed)
    print({"stage": "generated", "rows": len(demands)}, flush=True)
    taxonomy_categories = load_taxonomy(args.taxonomy)
    facet_frame = pd.read_csv(args.product_facets, dtype=str).fillna("")
    used_products = set(demands["product_reference"].astype(str))
    facet_frame = facet_frame[facet_frame["source_product_id"].astype(str).isin(used_products)]
    facets = build_product_facet_map(facet_frame)
    print({"stage": "facet_map", "keys": len(facets)}, flush=True)
    taxonomy_loader = load_json_taxonomy(args.taxonomy)
    rule = label_demands(demands, taxonomy_loader, product_facet_map=facets)
    rule["interpretation_method"] = "RULE_ALIAS"
    print({"stage": "rule_labeled", "rows": len(rule)}, flush=True)
    _write(rule, args.output_dir / "demand_5000_rule_labeled_v1.csv")

    sample = _sample(demands, 200, args.seed)
    _write(sample, args.output_dir / "model2_eval_sample_200_v1.csv")
    model = _model_name(args.model)
    model_available = bool(model and os.environ.get("MODEL2_PROVIDER", os.environ.get("MODEL1_PROVIDER", "ollama")) == "ollama")
    model_meta: dict[str, object] = {"provider": "ollama", "model": model or None, "status": "BLOCKED_NO_EXECUTABLE_MODEL"}
    model_result = _empty_model_frame(sample, "MODEL2_MODEL is not configured")
    sample_output = args.output_dir / "model2_llm_labeled_200_v1.csv"
    if args.reuse_llm_sample and sample_output.exists():
        model_result = pd.read_csv(sample_output, dtype=str).fillna("")
        model_meta = {"provider": "ollama", "model": model or None, "status": "COMPLETED_REUSED", "call_count": (len(sample) + args.batch_size - 1) // args.batch_size, "runtime_seconds": None}
    elif model_available:
        model_result, model_meta = _model_result(sample, args.taxonomy, args.product_facets, model, args.batch_size)
    _write(model_result, sample_output)
    print({"stage": "sample_written", "model_available": model_available}, flush=True)

    review_candidates = rule[rule["label_status"] != "LABELED"].copy()
    limited = review_candidates.iloc[: max(0, args.max_llm_calls * args.batch_size)].copy()
    full_model = None
    if model_available and not limited.empty:
        full_model, full_meta = _model_result(limited, args.taxonomy, args.product_facets, model, args.batch_size)
        model_meta["full_hybrid"] = full_meta
    hybrid = _build_hybrid(rule, limited, full_model, args.max_llm_calls, model_available)
    comparison = hybrid[["demand_id", "catalog_id", "category_id", "scenario_type", "label", "label_status", "hybrid_label", "hybrid_status", "interpretation_method", "hybrid_model_status"]].rename(columns={"label": "rule_label", "label_status": "rule_status"})
    if not model_result.empty:
        comparison = comparison.merge(model_result.rename(columns={"model_status": "llm_status", "model_warnings": "llm_warnings"})[["demand_id", "model_label", "llm_status", "llm_warnings"]], on="demand_id", how="left")
    _write(comparison, args.output_dir / "model2_rule_llm_hybrid_comparison_v1.csv")

    metadata_columns = ["demand_id", "profile_id", "generation_parent_id", "expected_facet_profile", "scenario_type", "data_origin", "reference_source", "augmentation_method"]
    _write(hybrid[metadata_columns], args.output_dir / "clustering_ground_truth_metadata_5000_v1.csv")
    feature_columns = ["demand_id", "catalog_id", "product_reference", "service_category_key", "service_category_name", "label", "labeling_status", "desired_price_min", "desired_price_max", "quantity", "is_substitutable", "unresolved_items", "interpretation_method", "taxonomy_version", "data_origin", "scenario_type"]
    clustering = hybrid.drop(columns=["label"]).rename(columns={"hybrid_label": "label", "hybrid_status": "labeling_status"})
    _write(clustering[feature_columns], args.output_dir / "clustering_input_grounded_5000_v1.csv")

    quality = quality_report(demands, set(demands["product_reference"]), set(taxonomy_categories))
    _write(demands, args.output_dir / "grounded_demand_5000_raw.csv")
    _write(quality, args.output_dir / "demand_5000_quality_report_v1.csv")
    report = quality_markdown(demands, quality) + "\n\n## Model 2 실행\n\n```json\n" + json.dumps(model_meta, ensure_ascii=False, indent=2, default=str) + "\n```\n"
    report += f"\n- Rule Labeling rows: {len(rule)}\n- Rule needs review: {int((rule['label_status'] != 'LABELED').sum())}\n- Hybrid LLM assisted: {int((hybrid['interpretation_method'] == 'HYBRID_RULE_LLM').sum())}\n- B export rows: {len(clustering)}\n- Runtime seconds: {time.perf_counter() - started:.3f}\n"
    (args.output_dir / "demand_5000_model2_report_v1.md").write_text(report, encoding="utf-8")
    print({"status": "COMPLETED", "rows": len(demands), "model_status": model_meta.get("status"), "output_dir": str(args.output_dir), "runtime_seconds": round(time.perf_counter() - started, 3)})


if __name__ == "__main__":
    main()
