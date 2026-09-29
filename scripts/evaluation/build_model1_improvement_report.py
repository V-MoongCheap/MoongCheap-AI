"""Aggregate reproducible Model 1 improvement experiments.

This report deliberately separates comparable operational metrics from quality
claims that still require an approved facet gold set. It does not promote a
candidate into the taxonomy or overwrite any existing artifact.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _model_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(row) for row in report.get("models", [])]


def _metric(row: dict[str, Any], key: str, default: Any = None) -> Any:
    return row.get(key, default)


def build_report(root: Path) -> dict[str, Any]:
    comparison_path = root / "data/processed/model1_domeggook_comparison_v6_clean_large/comparison_report_v1.json"
    consistency_path = root / "data/processed/model1_domeggook_consistency_qwen3_4b/comparison_report_v1.json"
    hybrid_v2_path = root / "data/processed/model1_domeggook_hybrid_v2_coverage/hybrid_report_v1.json"
    hybrid_v5_path = root / "data/processed/model1_domeggook_hybrid_v5_qwen3_1.7b/hybrid_report_v1.json"
    final_path = root / "data/processed/model1_domeggook_final_qwen3_4b/model1_final_report_v1.json"
    review_path = root / "data/processed/model1_review_kanana_210_fixed/multisource_candidate_review_queue_v1_human_reviewed_normalized.csv"

    comparison = _read_json(comparison_path)
    consistency = _read_json(consistency_path)
    hybrid_v2 = _read_json(hybrid_v2_path)
    hybrid_v5 = _read_json(hybrid_v5_path)
    final = _read_json(final_path)
    review = pd.read_csv(review_path, dtype=str).fillna("")

    models = []
    for row in _model_rows(comparison):
        models.append({
            "experiment": "single_pass_model_size",
            "model": _metric(row, "model"),
            "input_rows": comparison.get("input_rows"),
            "categories": _metric(row, "categories"),
            "successful_categories": _metric(row, "successful_categories"),
            "success_rate": round(_metric(row, "successful_categories", 0) / max(_metric(row, "categories", 1), 1), 4),
            "calls": _metric(row, "calls"),
            "candidate_rows": _metric(row, "candidate_rows"),
            "failure_rows": _metric(row, "failure_rows"),
            "runtime_seconds": _metric(row, "runtime_seconds"),
        })
    consistency_rows = _model_rows(consistency)
    if consistency_rows:
        row = consistency_rows[0]
        models.append({
            "experiment": "self_consistency_3_samples",
            "model": _metric(row, "model"),
            "input_rows": consistency.get("input_rows"),
            "categories": _metric(row, "categories"),
            "successful_categories": _metric(row, "successful_categories"),
            "success_rate": round(_metric(row, "successful_categories", 0) / max(_metric(row, "categories", 1), 1), 4),
            "calls": _metric(row, "calls"),
            "candidate_rows": _metric(row, "candidate_rows"),
            "failure_rows": _metric(row, "failure_rows"),
            "runtime_seconds": _metric(row, "runtime_seconds"),
            "consistency_attempts": _metric(row, "consistency_attempts"),
            "consistency_required_votes": _metric(row, "consistency_required_votes"),
        })

    review_counts = review["review_status"].value_counts().to_dict() if "review_status" in review else {}
    hybrid = {
        "experiment": "evidence_gated_hybrid",
        "same_input_products": hybrid_v5.get("coverage", {}).get("products"),
        "v2_coverage_ratio": hybrid_v2.get("coverage", {}).get("coverage_ratio"),
        "v5_coverage_ratio": hybrid_v5.get("coverage", {}).get("coverage_ratio"),
        "v2_unresolved_products": hybrid_v2.get("coverage", {}).get("unresolved_products"),
        "v5_unresolved_products": hybrid_v5.get("coverage", {}).get("unresolved_products"),
        "v2_hybrid_llm_rows": hybrid_v2.get("hybrid_llm_rows"),
        "v5_hybrid_llm_rows": hybrid_v5.get("hybrid_llm_rows"),
        "model_only_auto_promotion": False,
        "human_review_status_counts": review_counts,
    }
    return {
        "title": "Model 1 Improvement Experiments",
        "scope": "Offline comparison of existing reproducible artifacts on the 1,200-product Domeggook corpus",
        "metrics_warning": "Candidate count and operational success are not precision. Final quality requires an approved facet gold set.",
        "experiments": {
            "model_and_consistency": models,
            "hybrid": hybrid,
            "multi_source_and_strict_gate": {
                "input_products": final.get("input_products"),
                "covered_products": final.get("covered_products"),
                "unresolved_products": final.get("unresolved_products"),
                "coverage_ratio": round(final.get("covered_products", 0) / max(final.get("input_products", 1), 1), 4),
                "grounded_model_rows": final.get("grounded_model_rows"),
                "automatic_gate_accepted_rows": final.get("automatic_gate", {}).get("accepted_rows"),
                "automatic_gate_abstained_rows": final.get("automatic_gate", {}).get("abstained_rows"),
            },
        },
        "decisions": {
            "adopt": [
                "Evidence-gated Rule + LLM Hybrid: only evidence-backed model values can enter the candidate set.",
                "Strict schema/grounding gate: ambiguous or self-describing candidates abstain.",
                "Self-consistency is useful as an offline experiment, but not the default runtime because it increases calls and latency.",
            ],
            "not_adopt": [
                "Model-only taxonomy promotion: unsafe without evidence and human-approved gold.",
                "Qwen 2.5 7B as default over Qwen3 4B: same successful-category count with higher latency/failures in the comparable run.",
            ],
            "blocked_or_not_measurable": [
                "Fine-tuning: no sufficiently large, approved facet gold set and no stable train/validation/test split.",
                "Embedding reranking: no approved facet-level relevance labels for a defensible quality comparison.",
                "Human-quality precision/recall: current review artifacts are candidate review, not a complete approved gold set.",
            ],
        },
        "source_artifacts": [
            str(path.relative_to(root)) for path in (
                comparison_path, consistency_path, hybrid_v2_path, hybrid_v5_path, final_path, review_path
            )
        ],
    }


def _markdown(report: dict[str, Any]) -> str:
    models = report["experiments"]["model_and_consistency"]
    lines = [
        "# Model 1 Improvement Experiment Results",
        "",
        report["scope"],
        "",
        "> Candidate counts and operational success are not quality precision. Final quality claims require an approved facet Gold Set.",
        "",
        "## Model and execution techniques",
        "",
        "| Experiment | Model | Success categories | Calls | Failures | Runtime (s) |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for row in models:
        lines.append(
            f"| {row['experiment']} | {row['model']} | {row['successful_categories']}/{row['categories']} ({row['success_rate']:.1%}) | {row['calls']} | {row['failure_rows']} | {row['runtime_seconds']} |"
        )
    hybrid = report["experiments"]["hybrid"]
    lines += [
        "",
        "## Hybrid and gate results",
        "",
        f"- Hybrid V2 coverage: `{hybrid['v2_coverage_ratio']}` ({hybrid['v2_unresolved_products']} unresolved products).",
        f"- Hybrid V5 coverage: `{hybrid['v5_coverage_ratio']}` ({hybrid['v5_unresolved_products']} unresolved products).",
        f"- Evidence-backed LLM rows: V2 `{hybrid['v2_hybrid_llm_rows']}`, V5 `{hybrid['v5_hybrid_llm_rows']}`.",
        "- Model-only automatic promotion: `False`.",
        "",
        "## Decisions",
        "",
    ]
    for label, values in report["decisions"].items():
        lines.append(f"### {label}")
        lines.extend(f"- {value}" for value in values)
        lines.append("")
    lines += ["## Source artifacts", ""]
    lines.extend(f"- `{path}`" for path in report["source_artifacts"])
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    report = build_report(args.root)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "model1_improvement_experiment_report_v1.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (args.output_dir / "MODEL1_IMPROVEMENT_EXPERIMENTS_V1.md").write_text(
        _markdown(report), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
