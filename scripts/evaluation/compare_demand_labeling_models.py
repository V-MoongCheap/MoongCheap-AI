"""Compare Demand labeling models on one fixed, grounded evaluation sample."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from moongcheap_ai.data_foundation.labeling import load_taxonomy
from report_demand_labeling_metrics import _metric_row


def _read(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str).fillna("")


def _attach_metadata(frame: pd.DataFrame, metadata: pd.DataFrame) -> pd.DataFrame:
    columns = ["demand_id", "category_id", "expected_facet_profile", "scenario_type", "profile_id", "product_reference"]
    available = [column for column in columns if column in metadata.columns]
    return frame.drop(columns=[column for column in available if column != "demand_id" and column in frame.columns], errors="ignore").merge(
        metadata[available], on="demand_id", how="left", suffixes=("", "_reference")
    )


def _filter_sample(frame: pd.DataFrame, sample_ids: set[str]) -> pd.DataFrame:
    return frame[frame["demand_id"].astype(str).isin(sample_ids)].copy()


def _align_model_output(frame: pd.DataFrame, sample: pd.DataFrame) -> pd.DataFrame:
    """Restore omitted model rows so every model is measured on the same sample."""
    columns = ["demand_id", "model_label", "model_status"]
    available = [column for column in columns if column in frame.columns]
    output = sample[["demand_id"]].merge(frame[available], on="demand_id", how="left")
    output["model_label"] = output.get("model_label", "").fillna("")
    output["model_status"] = output.get("model_status", "").replace("", "MODEL_FAILURE").fillna("MODEL_FAILURE")
    return output


def _execution_meta(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def build_comparison(
    input_dir: Path,
    taxonomy_path: Path,
    model_files: list[tuple[str, Path, Path | None]],
    rule_file: Path,
    hybrid_file: Path,
    sample_file: Path,
) -> pd.DataFrame:
    taxonomy = load_taxonomy(taxonomy_path)
    sample = _read(sample_file)
    sample_ids = set(sample["demand_id"].astype(str))
    metadata = sample[["demand_id", "category_id", "expected_facet_profile", "scenario_type", "profile_id", "product_reference"]]

    rule = _filter_sample(_read(rule_file), sample_ids)
    rule = _attach_metadata(rule, metadata)
    rule_metrics = _metric_row("RULE_ONLY", rule, "label_status", "label", taxonomy, model_calls=0, model_intervention_rows=0)
    rule_metrics["runtime_seconds"] = 0.0
    rows = [rule_metrics]

    hybrid = _filter_sample(_read(hybrid_file), sample_ids)
    hybrid = _attach_metadata(hybrid, metadata)
    hybrid_metrics = _metric_row(
            "HYBRID_RULE_FIRST",
            hybrid,
            "hybrid_status",
            "hybrid_label",
            taxonomy,
            model_failures=int(hybrid.get("hybrid_model_status", pd.Series(dtype=str)).eq("MODEL_FAILURE").sum()),
            model_calls=_execution_meta(input_dir / "model2_only_execution_v1.json").get("model_calls"),
            model_intervention_rows=int(hybrid.get("hybrid_model_status", pd.Series(dtype=str)).isin(["LLM_ASSISTED", "MODEL_FAILURE"]).sum()),
        )
    hybrid_metrics["runtime_seconds"] = None
    rows.append(hybrid_metrics)

    for display_name, path, execution_path in model_files:
        model = _align_model_output(_read(path), sample)
        model = _attach_metadata(model, metadata)
        meta = _execution_meta(execution_path) if execution_path else {}
        model_metrics = _metric_row(
                display_name,
                model,
                "model_status",
                "model_label",
                taxonomy,
                model_failures=int(model["model_status"].eq("MODEL_FAILURE").sum()),
                model_calls=meta.get("model_calls"),
                model_intervention_rows=int(model["model_status"].ne("MODEL_FAILURE").sum()),
            )
        model_metrics["runtime_seconds"] = meta.get("runtime_seconds")
        rows.append(model_metrics)
    return pd.DataFrame(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--taxonomy", type=Path, required=True)
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--rule", type=Path, required=True)
    parser.add_argument("--hybrid", type=Path, required=True)
    parser.add_argument("--model", action="append", nargs=3, metavar=("NAME", "CSV", "META"), required=True)
    parser.add_argument("--output-csv", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    args = parser.parse_args()

    model_files = [(name, Path(csv), Path(meta) if meta else None) for name, csv, meta in args.model]
    result = build_comparison(args.input_dir, args.taxonomy, model_files, args.rule, args.hybrid, args.sample)
    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output_csv, index=False, encoding="utf-8-sig")
    lines = [
        "# Demand Labeling Model Comparison",
        "",
        "All methods use the same 200-row grounded evaluation sample and the same taxonomy.",
        "The expected profile is synthetic evaluation metadata, not observed-user ground truth.",
        "",
        "```",
        result.to_string(index=False),
        "```",
        "",
        "- HP: same profile rows receive the same label.",
        "- HN: different profile rows in the same category receive different labels.",
        "- diagnostic_agreement: agreement with the generated expected profile; it is not human-annotated accuracy.",
        "- model_failure_rows and review_rows must be considered together with agreement.",
        "- Recommended production structure: RULE_ONLY first, then call an LLM only for unresolved or conflicting rows, validate every returned code against the taxonomy, and route failures to review.",
        "- No tested LLM-only model is promoted to production from this synthetic benchmark; it is not human-annotated gold data.",
    ]
    args.output_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(result.to_dict("records"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
