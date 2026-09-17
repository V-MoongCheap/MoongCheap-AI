"""Split grounded Model 2 demands into deterministic evaluation artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


EVAL_ONLY_COLUMNS = {
    "expected_facet_profile", "profile_id", "generation_parent_id", "source_review_id",
    "source_keyword", "sampling_seed",
}
SPLITS = {"dev": 300, "holdout": 150, "challenge": 150}


def _allocate(total: int, sizes: pd.Series) -> dict[tuple[str, str], int]:
    exact = sizes / sizes.sum() * total
    result = {key: int(value) for key, value in exact.items()}
    for key in exact.sort_values(ascending=False).index[: total - sum(result.values())]:
        result[key] += 1
    return result


def split_frame(frame: pd.DataFrame, seed: int) -> dict[str, pd.DataFrame]:
    required = {"demand_id", "category_id", "scenario_type", "expected_facet_profile"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError("demand input missing columns: " + ", ".join(missing))
    work = frame.fillna("").copy()
    if work["demand_id"].duplicated().any():
        raise ValueError("demand_id must be unique")
    strata = work.groupby(["category_id", "scenario_type"], sort=True).size()
    remaining = work.copy()
    result: dict[str, pd.DataFrame] = {}
    for index, (name, size) in enumerate(SPLITS.items()):
        allocation = _allocate(size, strata)
        pieces = []
        for key, count in allocation.items():
            if count == 0:
                continue
            candidates = remaining[
                remaining["category_id"].eq(key[0]) & remaining["scenario_type"].eq(key[1])
            ]
            if len(candidates) < count:
                raise ValueError(f"not enough rows in stratum {key} for {name}")
            pieces.append(candidates.sample(n=count, random_state=seed + index))
        selected = pd.concat(pieces).sort_values("demand_id").reset_index(drop=True)
        result[name] = selected
        remaining = remaining[~remaining["demand_id"].isin(selected["demand_id"])]
        strata = remaining.groupby(["category_id", "scenario_type"], sort=True).size()
    return result


def build(input_path: Path, output_dir: Path, seed: int = 42) -> dict[str, object]:
    frame = pd.read_csv(input_path, dtype=str, encoding="utf-8-sig").fillna("")
    splits = split_frame(frame, seed)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary: dict[str, object] = {"input_rows": len(frame), "seed": seed, "splits": {}}
    for name, selected in splits.items():
        gold_columns = [
            column for column in (
                "demand_id", "catalog_id", "product_reference", "category_id", "scenario_type",
                "extra_requirement", "expected_facet_profile", "product_base_facets",
                "source_product_id", "source_document_id", "source_evidence_text", "data_origin",
            ) if column in selected.columns
        ]
        gold = selected[gold_columns].copy()
        gold["review_decision"] = ""
        gold["review_note"] = ""
        runtime = selected.drop(columns=[column for column in EVAL_ONLY_COLUMNS if column in selected], errors="ignore")
        runtime.to_csv(output_dir / f"model2_{name}_input.csv", index=False, encoding="utf-8-sig")
        gold.to_csv(output_dir / f"model2_{name}_gold_candidate.csv", index=False, encoding="utf-8-sig")
        summary["splits"][name] = {
            "rows": len(selected),
            "categories": int(selected["category_id"].nunique()),
            "scenarios": selected["scenario_type"].value_counts().to_dict(),
            "runtime_has_expected_profile": "expected_facet_profile" in runtime,
        }
    review = pd.read_csv(output_dir / "model2_challenge_gold_candidate.csv", dtype=str, encoding="utf-8-sig")
    review.to_csv(output_dir / "model2_human_review_queue.csv", index=False, encoding="utf-8-sig")
    (output_dir / "model2_evaluation_split_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    print(json.dumps(build(args.input, args.output_dir, args.seed), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
