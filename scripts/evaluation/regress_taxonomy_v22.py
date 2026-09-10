"""Run the fixed 200-row Rule/Alias regression for Taxonomy V2.2."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from moongcheap_ai.data_foundation.labeling import build_product_facet_map, label_demands, load_taxonomy
from report_demand_labeling_metrics import _metric_row


def _read(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str).fillna("")


def _alias_hits(sample: pd.DataFrame, audit_path: Path) -> tuple[int, int]:
    audit = _read(audit_path)
    applied = audit[audit["apply_status"].eq("APPLIED")]
    hits = 0
    corrected_hits = 0
    for _, row in applied.iterrows():
        surface = str(row.get("candidate_expression", "")).strip()
        if not surface:
            continue
        matched = sample["extra_requirement"].astype(str).str.contains(surface, regex=False, na=False)
        count = int(matched.sum())
        hits += count
        if str(row.get("corrected_value_candidate", "")).strip():
            corrected_hits += count
    return hits, corrected_hits


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--v21-taxonomy", type=Path, required=True)
    parser.add_argument("--v22-taxonomy", type=Path, required=True)
    parser.add_argument("--v21-rule", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--product-facets", type=Path, required=True)
    parser.add_argument("--output-csv", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    args = parser.parse_args()
    sample = _read(args.sample)
    v21 = load_taxonomy(args.v21_taxonomy)
    v22 = load_taxonomy(args.v22_taxonomy)
    product_facets = build_product_facet_map(_read(args.product_facets))
    existing = _read(args.v21_rule)
    existing = existing[existing["demand_id"].isin(set(sample["demand_id"]))].copy()
    v21_metrics = _metric_row("V2.1_RULE_ONLY", existing, "label_status", "label", v21, model_calls=0, model_intervention_rows=0)
    v22_result = label_demands(sample, v22, product_facet_map=product_facets)
    v22_metrics = _metric_row("V2.2_RULE_ALIAS_ONLY", v22_result, "label_status", "label", v22, model_calls=0, model_intervention_rows=0)
    hits, corrected_hits = _alias_hits(sample, args.audit)
    metrics = pd.DataFrame([v21_metrics, v22_metrics])
    metrics["alias_hit"] = [0, hits]
    metrics["corrected_alias_hit"] = [0, corrected_hits]
    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    metrics.to_csv(args.output_csv, index=False, encoding="utf-8-sig")
    v22 = v22_metrics
    lines = [
        "# Taxonomy V2.2 Demand Regression", "",
        "동일한 grounded 200건을 사용했으며 LLM benchmark는 재실행하지 않았다.", "",
        "```", metrics.to_string(index=False), "```", "",
        f"- V2.1 Rule-only diagnostic agreement: {v21_metrics['diagnostic_agreement']:.4f}",
        f"- V2.2 Rule/Alias-only diagnostic agreement: {v22['diagnostic_agreement']:.4f}",
        f"- Alias hit: {hits}", f"- Corrected alias hit: {corrected_hits}",
        f"- V2.2 unresolved / conflict / invalid code: {v22['unresolved_rows']} / {v22['conflict_scenario_rows']} / {v22['out_of_taxonomy_rows']}",
    ]
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"v21": v21_metrics, "v22": v22_metrics, "alias_hit": hits, "corrected_alias_hit": corrected_hits}, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
