"""Evaluate the Rule/Alias Model 2 baseline against generated expectations.

The report is diagnostic only: expected profiles are generation metadata, not
human-verified labels.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def _json(value: object) -> dict:
    try:
        parsed = json.loads(str(value))
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def _matches(label: object, expected: object, facet_order: list[str] | None = None, defaults: object = None) -> bool:
    actual = [part for part in str(label or "").split("-") if part.isdigit()]
    expected_values = _json(defaults)
    expected_values.update(_json(expected))
    if facet_order is None:
        expected_codes = [str(item.get("code", 0)) for item in expected_values.values()]
    else:
        if len(actual) != len(facet_order):
            return False
        expected_codes = [str(expected_values.get(name, {}).get("code", 0)) for name in facet_order]
    if not actual or len(actual) != len(expected_codes):
        return False
    # A generated profile specifies only selected facets; ALL is intentionally
    # unconstrained for this diagnostic comparison.
    return all(expected_code == "0" or actual[index] == expected_code for index, expected_code in enumerate(expected_codes))


def evaluate(labeled_path: Path, split_dir: Path, output: Path, taxonomy_path: Path | None = None) -> pd.DataFrame:
    labeled = pd.read_csv(labeled_path, dtype=str, encoding="utf-8-sig").fillna("")
    taxonomy = {}
    if taxonomy_path:
        taxonomy = json.loads(taxonomy_path.read_text(encoding="utf-8"))
    category_orders = {
        str(category["category_id"]): [str(facet["name"]) for facet in sorted(category.get("facets", []), key=lambda item: int(item.get("order", 0)))]
        for category in taxonomy.get("categories", [])
    }
    rows: list[dict[str, object]] = []
    for split in ("dev", "holdout", "challenge"):
        gold = pd.read_csv(split_dir / f"model2_{split}_gold_candidate.csv", dtype=str, encoding="utf-8-sig").fillna("")
        joined = gold.merge(labeled[["demand_id", "label", "label_status", "label_warnings"]], on="demand_id", how="left")
        comparable = joined["label"].ne("")
        def expected_for(row: pd.Series) -> object:
            # No-text demands should be judged against product defaults only;
            # the generator's selected profile is not a user requirement there.
            return "{}" if str(row.get("scenario_type")) == "NO_EXTRA_REQUIREMENT" else row.get("expected_facet_profile")

        agreements = joined.apply(lambda row: _matches(row.get("label"), expected_for(row), category_orders.get(str(row.get("category_id"))), row.get("product_base_facets")), axis=1)
        for scenario, group in joined.groupby("scenario_type", sort=True):
            rows.append({
                "split": split,
                "scenario_type": scenario,
                "rows": len(group),
                "labeled_rows": int(group["label"].ne("").sum()),
                "expected_profile_agreement": round(float(agreements.loc[group.index].mean()), 4),
                "review_rows": int(group["label_status"].str.contains("REVIEW|FAILURE|BLOCKED", case=False, regex=True).sum()),
            })
        rows.append({
            "split": split,
            "scenario_type": "__TOTAL__",
            "rows": len(joined),
            "labeled_rows": int(comparable.sum()),
            "expected_profile_agreement": round(float(agreements.mean()), 4),
            "review_rows": int(joined["label_status"].str.contains("REVIEW|FAILURE|BLOCKED", case=False, regex=True).sum()),
        })
    result = pd.DataFrame(rows)
    output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output, index=False, encoding="utf-8-sig")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labeled", type=Path, required=True)
    parser.add_argument("--split-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--taxonomy", type=Path)
    args = parser.parse_args()
    print(evaluate(args.labeled, args.split_dir, args.output, args.taxonomy).to_string(index=False))


if __name__ == "__main__":
    main()
