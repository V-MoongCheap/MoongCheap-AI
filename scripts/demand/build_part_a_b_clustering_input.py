"""Build the Part A -> Part B clustering handoff from runtime output."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


LABELED_STATUSES = {"PARSED", "NONE", "NOT_APPLICABLE"}
REVIEW_STATUSES = {"PASSTHROUGH", "CONFLICT", "REVIEW", "TAXONOMY_AMBIGUOUS"}


def _json_list(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "[]"
    text = str(value).strip()
    if not text or text == "[]":
        return "[]"
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return json.dumps([text], ensure_ascii=False)
    return json.dumps(parsed if isinstance(parsed, list) else [parsed], ensure_ascii=False, separators=(",", ":"))


def build(raw_path: Path, runtime_path: Path, output_path: Path, metadata_path: Path) -> dict[str, int]:
    raw = pd.read_csv(raw_path, dtype=str, encoding="utf-8-sig").fillna("")
    runtime = pd.read_csv(runtime_path, dtype=str, encoding="utf-8-sig").fillna("")
    for name, frame in (("raw", raw), ("runtime", runtime)):
        if "demand_id" not in frame.columns:
            raise ValueError(f"{name} is missing demand_id")
        if frame["demand_id"].duplicated().any():
            raise ValueError(f"{name} contains duplicate demand_id")
    if len(raw) != len(runtime):
        raise ValueError(f"row count mismatch: raw={len(raw)} runtime={len(runtime)}")

    runtime_columns = [
        column for column in (
            "demand_id", "catalog_id", "category_id", "label", "status",
            "constraints", "reasonCodes", "taxonomyVersion", "parserVersion",
            "effectiveRequirementMode", "facet_values", "interpretation_method",
        ) if column in runtime.columns
    ]
    joined = raw.merge(runtime[runtime_columns], on="demand_id", how="left", validate="one_to_one", suffixes=("", "_runtime"))
    if joined["status"].eq("").any():
        raise ValueError("runtime output is missing rows for one or more demand_id values")

    status = joined["status"].astype(str)
    unknown = sorted(set(status) - LABELED_STATUSES - REVIEW_STATUSES)
    if unknown:
        raise ValueError("unknown runtime status: " + ", ".join(unknown))

    joined["labeling_status"] = status.map(
        lambda value: "LABELED" if value in LABELED_STATUSES else "LABELED_WITH_REVIEW"
    )
    joined["unresolved_items"] = joined.apply(
        lambda row: "[]" if row["status"] in LABELED_STATUSES else _json_list(row.get("reasonCodes", "")),
        axis=1,
    )

    feature_columns = [
        "demand_id", "catalog_id", "category_id", "extra_requirement",
        "desired_price_min", "desired_price_max", "quantity", "is_substitutable",
        "label", "labeling_status", "unresolved_items", "effectiveRequirementMode",
        "taxonomyVersion", "data_origin", "scenario_type",
    ]
    missing = [column for column in feature_columns if column not in joined.columns]
    if missing:
        raise ValueError("raw/runtime handoff missing columns: " + ", ".join(missing))

    metadata_columns = [
        column for column in (
            "demand_id", "profile_id", "generation_parent_id", "expected_facet_profile",
            "scenario_type", "data_origin", "reference_source", "augmentation_method",
            "source_product_id", "source_review_id", "source_keyword", "source_document_id",
            "generation_method", "source_evidence_text", "sampling_seed",
        ) if column in joined.columns
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    joined[feature_columns].to_csv(output_path, index=False, encoding="utf-8-sig")
    joined[metadata_columns].to_csv(metadata_path, index=False, encoding="utf-8-sig")

    return {
        "rows": len(joined),
        "labeled_rows": int((joined["labeling_status"] == "LABELED").sum()),
        "review_rows": int((joined["labeling_status"] == "LABELED_WITH_REVIEW").sum()),
        "conflict_rows": int((status == "CONFLICT").sum()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the Part A to Part B clustering handoff")
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.raw, args.runtime, args.output, args.metadata), ensure_ascii=False))


if __name__ == "__main__":
    main()
