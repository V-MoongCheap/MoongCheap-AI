"""Summarize Rule, Model Only, and Hybrid Demand labeling metrics."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from moongcheap_ai.data_foundation.labeling import load_taxonomy


def _json(value: object) -> object:
    try:
        return json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return {}


def _expected_codes(row: pd.Series, taxonomy) -> dict[str, int]:
    category = taxonomy.category(row.get("category_id", "")) or {}
    expected = _json(row.get("expected_facet_profile", "{}"))
    expected = expected if isinstance(expected, dict) else {}
    facets = sorted(category.get("facets", []), key=lambda item: int(item.get("order", 0)))
    return {str(facet["name"]): int(expected.get(str(facet["name"]), {}).get("code", 0)) for facet in facets}


def _label_matches_expected(label: object, row: pd.Series, taxonomy) -> bool | None:
    if label is None or pd.isna(label) or not str(label).strip():
        return None
    codes = [int(part) for part in str(label).split("-") if str(part).strip().isdigit()]
    expected = _expected_codes(row, taxonomy)
    category = taxonomy.category(row.get("category_id", "")) or {}
    facets = sorted(category.get("facets", []), key=lambda item: int(item.get("order", 0)))
    if len(codes) != len(facets):
        return False
    return all(codes[index] == expected[str(facet["name"])] for index, facet in enumerate(facets) if expected[str(facet["name"])] != 0)


def _unresolved(value: object) -> bool:
    parsed = _json(value)
    return bool(parsed) if isinstance(parsed, (list, dict)) else bool(str(value).strip())


def _pair_metrics(frame: pd.DataFrame, label_column: str) -> dict[str, object]:
    """Measure same-profile positives and same-product hard negatives."""
    hp_pairs = hp_correct = hn_pairs = hn_correct = 0
    if "profile_id" in frame:
        for _, group in frame.groupby("profile_id", sort=False):
            labels = group[label_column].fillna("").astype(str).tolist()
            for left in range(len(labels)):
                for right in range(left + 1, len(labels)):
                    if labels[left] and labels[right]:
                        hp_pairs += 1
                        hp_correct += labels[left] == labels[right]
    if "category_id" in frame and "profile_id" in frame:
        for _, group in frame.groupby(["category_id"], sort=False):
            records = group[["profile_id", label_column]].fillna("").to_dict("records")
            for left in range(len(records)):
                for right in range(left + 1, len(records)):
                    if records[left]["profile_id"] != records[right]["profile_id"] and records[left][label_column] and records[right][label_column]:
                        hn_pairs += 1
                        hn_correct += records[left][label_column] != records[right][label_column]
    return {
        "hp_pairs": hp_pairs,
        "hp_correct": hp_correct,
        "hp_rate": round(hp_correct / hp_pairs, 4) if hp_pairs else None,
        "hn_pairs": hn_pairs,
        "hn_correct": hn_correct,
        "hn_rate": round(hn_correct / hn_pairs, 4) if hn_pairs else None,
        "tp": hp_correct,
        "tn": hn_correct,
        "fp": hn_pairs - hn_correct,
        "fn": hp_pairs - hp_correct,
        "pair_precision": round(hp_correct / (hp_correct + hn_pairs - hn_correct), 4) if hp_correct + hn_pairs - hn_correct else None,
        "pair_recall": round(hp_correct / hp_pairs, 4) if hp_pairs else None,
        "pair_f1": round(2 * hp_correct / (2 * hp_correct + hn_pairs - hn_correct + hp_pairs - hp_correct), 4) if 2 * hp_correct + hn_pairs - hn_correct + hp_pairs - hp_correct else None,
        "pair_accuracy": round((hp_correct + hn_correct) / (hp_pairs + hn_pairs), 4) if hp_pairs + hn_pairs else None,
        "pair_error_rate": round((hn_pairs - hn_correct + hp_pairs - hp_correct) / (hp_pairs + hn_pairs), 4) if hp_pairs + hn_pairs else None,
        "pair_coverage": round((hp_pairs + hn_pairs) / (len(frame) * (len(frame) - 1) / 2), 4) if len(frame) > 1 else None,
    }


def _metric_row(method: str, frame: pd.DataFrame, status_column: str, label_column: str, taxonomy, model_failures: int = 0, model_calls: object = None, model_intervention_rows: object = None) -> dict[str, object]:
    labeled = frame[label_column].fillna("").astype(str).str.strip().ne("")
    status = frame[status_column].fillna("").astype(str)
    diagnostic = [_label_matches_expected(label, row, taxonomy) for label, (_, row) in zip(frame[label_column], frame.iterrows())]
    diagnostic_values = [value for value in diagnostic if value is not None]
    return {
        "method": method,
        "dataset_rows": len(frame),
        "labeled_rows": int(labeled.sum()),
        "review_rows": int(status.str.contains("REVIEW|FAILURE|LIMIT|BLOCKED", case=False, regex=True).sum()),
        "unresolved_rows": int(frame.get("unresolved_items", pd.Series([], dtype=str)).map(_unresolved).sum()) if "unresolved_items" in frame else None,
        "model_failure_rows": model_failures,
        "model_intervention_rows": model_intervention_rows,
        "diagnostic_agreement_rows": sum(value is True for value in diagnostic_values),
        "diagnostic_comparable_rows": len(diagnostic_values),
        "diagnostic_agreement": round(sum(value is True for value in diagnostic_values) / len(diagnostic_values), 4) if diagnostic_values else None,
        "normal_scenario_rows": int(frame.get("scenario_type", pd.Series([], dtype=str)).astype(str).str.startswith("NORMAL").sum()) if "scenario_type" in frame else None,
        "ambiguous_scenario_rows": int(frame.get("scenario_type", pd.Series([], dtype=str)).eq("AMBIGUOUS").sum()) if "scenario_type" in frame else None,
        "conflict_scenario_rows": int(frame.get("scenario_type", pd.Series([], dtype=str)).eq("CONFLICT").sum()) if "scenario_type" in frame else None,
        "out_of_taxonomy_rows": int(frame.get("scenario_type", pd.Series([], dtype=str)).eq("OUT_OF_TAXONOMY").sum()) if "scenario_type" in frame else None,
        "model_calls": model_calls,
        **_pair_metrics(frame, label_column),
    }


def build_metrics(input_dir: Path, taxonomy_path: Path) -> pd.DataFrame:
    taxonomy = load_taxonomy(taxonomy_path)
    raw = pd.read_csv(input_dir / "grounded_demand_5000_raw.csv", dtype=str).fillna("")
    metadata = raw[["demand_id", "expected_facet_profile", "scenario_type", "profile_id", "product_reference"]]
    rule = pd.read_csv(input_dir / "demand_5000_rule_labeled_v1.csv", dtype=str).fillna("").merge(metadata, on="demand_id", how="left", suffixes=("", "_raw"))
    hybrid = pd.read_csv(input_dir / "model2_rule_llm_hybrid_comparison_v1.csv", dtype=str).fillna("").merge(metadata[["demand_id", "expected_facet_profile", "profile_id", "product_reference"]], on="demand_id", how="left")
    full_model_path = input_dir / "model2_only_labeled_5000_v1.csv"
    model_path = full_model_path if full_model_path.exists() else input_dir / "model2_llm_labeled_200_v1.csv"
    llm = pd.read_csv(model_path, dtype=str).fillna("")
    if "profile_id" not in llm.columns:
        llm = llm.merge(metadata, on="demand_id", how="left")
    execution_meta = {}
    meta_path = input_dir / "model2_only_execution_v1.json"
    if meta_path.exists():
        execution_meta = json.loads(meta_path.read_text(encoding="utf-8"))
    model_method = "MODEL_ONLY_FULL_5000" if full_model_path.exists() else "MODEL_ONLY_SAMPLE_200"
    model_calls = execution_meta.get("model_calls", 4 if model_method.endswith("200") else None)
    rows = [
        _metric_row("RULE_BASELINE", rule, "label_status", "label", taxonomy, model_calls=0, model_intervention_rows=0),
        _metric_row(model_method, llm, "model_status", "model_label", taxonomy, model_failures=int(llm["model_status"].eq("MODEL_FAILURE").sum()), model_calls=model_calls, model_intervention_rows=int(llm["model_status"].ne("MODEL_FAILURE").sum())),
        _metric_row("HYBRID_RULE_FIRST", hybrid, "hybrid_status", "hybrid_label", taxonomy, model_failures=int(hybrid["hybrid_model_status"].eq("MODEL_FAILURE").sum()), model_calls=1, model_intervention_rows=int(hybrid["hybrid_model_status"].isin(["LLM_ASSISTED", "MODEL_FAILURE"]).sum())),
    ]
    result = pd.DataFrame(rows)
    result.attrs["rule_rows"] = len(rule)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Report Demand labeling method metrics")
    parser.add_argument("--input-dir", type=Path, default=Path("data/processed/demand_5000_v1"))
    parser.add_argument("--taxonomy", type=Path, default=Path("data/processed/downstream_v2_1/taxonomy_candidate_v2_1.json"))
    args = parser.parse_args()
    metrics = build_metrics(args.input_dir, args.taxonomy)
    output_csv = args.input_dir / "demand_labeling_method_metrics_v1.csv"
    output_md = args.input_dir / "demand_labeling_method_metrics_v1.md"
    metrics.to_csv(output_csv, index=False, encoding="utf-8-sig")
    lines = [
        "# Demand Labeling 방식별 지표", "",
        "Rule Baseline, Model Only, Hybrid를 각각 실제 산출물 범위 기준으로 집계했습니다.",
        "`diagnostic_agreement`는 생성 시 사용한 expected facet profile과의 비교이며 Human Gold Accuracy가 아닙니다.", "",
        "```", metrics.to_string(index=False), "```", "",
        "## 해석", "",
        "- Rule Baseline: Alias/규칙으로 전체를 빠르게 처리하며 검토 대상은 별도 표시합니다.",
        "- Model Only: 200건 Sample에 실제 Model 2를 적용한 결과입니다. 모델 실패는 정상 Label로 간주하지 않습니다.",
        "- Hybrid: Rule 성공 건은 Rule을 사용하고, 검토 대상만 제한적으로 Model을 호출합니다.",
        "- HP(Hard Positive): 같은 Profile의 표현 변형 쌍이 같은 Label인지 측정합니다.",
        "- HN(Hard Negative): 같은 Category의 서로 다른 Profile 쌍이 다른 Label인지 측정합니다.",
        "- TP/TN/FP/FN과 Pair Precision·Recall·F1·Accuracy·Error Rate·Coverage도 같은 쌍 기준으로 계산합니다.",
        "- 가격·수량·대체 가능 여부는 Labeling 정확도 지표가 아니라 Synthetic 정책 값입니다.",
    ]
    output_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(metrics.to_dict("records"))


if __name__ == "__main__":
    main()
