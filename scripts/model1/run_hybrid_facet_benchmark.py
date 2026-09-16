"""Compare Rule-only, model-only, and evidence-gated Hybrid Facet candidates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from moongcheap_ai.data_foundation.facet_hybrid import (
    benchmark_candidate_sets,
    build_rule_candidates,
    merge_rule_model_candidates,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True, help="multisource model input JSONL")
    parser.add_argument("--model-candidates", type=Path, help="model_candidates_v1.csv, optional")
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed/model1_hybrid_benchmark"))
    parser.add_argument("--min-support", type=int, default=1)
    parser.add_argument("--min-ratio", type=float, default=0.0)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    inputs = pd.read_json(args.input, lines=True).fillna("")
    model = pd.read_csv(args.model_candidates, dtype=str).fillna("") if args.model_candidates and args.model_candidates.exists() else pd.DataFrame()
    rule = build_rule_candidates(inputs, min_support=args.min_support, min_ratio=args.min_ratio)
    hybrid = merge_rule_model_candidates(rule, model)
    metrics = benchmark_candidate_sets(rule, model, hybrid)
    rule.to_csv(args.output_dir / "rule_candidates_v1.csv", index=False, encoding="utf-8-sig")
    hybrid.to_csv(args.output_dir / "hybrid_candidates_v1.csv", index=False, encoding="utf-8-sig")
    (args.output_dir / "hybrid_benchmark_metrics_v1.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
