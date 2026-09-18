"""Apply validated reviewer corrections to an auditable product-Facet mapping.

Only ``EDIT`` rows are applied. ``UNCERTAIN`` and blank decisions deliberately
leave the original mapping untouched: a missing product fact must not become a
guessed Facet value merely because it was reviewed.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


MAPPING_KEY = ["catalog_id", "category_id", "facet_name"]
REVIEW_REQUIRED = {
    *MAPPING_KEY,
    "review_decision",
    "reviewed_value",
    "reviewed_code",
}
MAPPING_REQUIRED = {
    *MAPPING_KEY,
    "value",
    "value_code",
    "mapping_status",
    "mapping_reason",
}


def _taxonomy_values(path: Path) -> dict[tuple[str, str, str], str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    values: dict[tuple[str, str, str], str] = {}
    for category in payload.get("categories", []):
        category_id = str(category["category_id"])
        for facet in category.get("facets", []):
            facet_name = str(facet["name"])
            for value in facet.get("values", []):
                values[(category_id, facet_name, str(value["code"]))] = str(
                    value["value"]
                )
    if not values:
        raise ValueError("taxonomy contains no Facet values")
    return values


def apply(
    mapping_path: Path,
    review_path: Path,
    taxonomy_path: Path,
    output_path: Path,
    report_path: Path,
) -> dict[str, int]:
    mapping = pd.read_csv(mapping_path, dtype=str, encoding="utf-8-sig").fillna("")
    review = pd.read_csv(review_path, dtype=str, encoding="utf-8-sig").fillna("")
    if missing := sorted(MAPPING_REQUIRED - set(mapping.columns)):
        raise ValueError("mapping is missing columns: " + ", ".join(missing))
    if missing := sorted(REVIEW_REQUIRED - set(review.columns)):
        raise ValueError("review is missing columns: " + ", ".join(missing))
    if mapping.duplicated(MAPPING_KEY).any():
        raise ValueError("mapping contains duplicate catalog/category/facet keys")

    edits = review.loc[review["review_decision"].eq("EDIT")].copy()
    if edits.duplicated(MAPPING_KEY).any():
        raise ValueError("review contains duplicate EDIT catalog/category/facet keys")
    if edits[["reviewed_value", "reviewed_code"]].eq("").any(axis=None):
        raise ValueError("every EDIT row requires reviewed_value and reviewed_code")

    taxonomy_values = _taxonomy_values(taxonomy_path)
    for row in edits.itertuples(index=False):
        key = (str(row.category_id), str(row.facet_name), str(row.reviewed_code))
        expected_value = taxonomy_values.get(key)
        if expected_value is None:
            raise ValueError(f"reviewed code is absent from taxonomy: {key}")
        if expected_value != str(row.reviewed_value):
            raise ValueError(
                "reviewed value does not match taxonomy: "
                f"{key} expected={expected_value!r} received={row.reviewed_value!r}"
            )

    result = mapping.copy()
    index_by_key = {
        tuple(row[column] for column in MAPPING_KEY): index
        for index, row in result.iterrows()
    }
    missing_keys = [
        tuple(row[column] for column in MAPPING_KEY)
        for _, row in edits.iterrows()
        if tuple(row[column] for column in MAPPING_KEY) not in index_by_key
    ]
    if missing_keys:
        raise ValueError(f"EDIT rows are absent from mapping: {missing_keys[:5]}")

    for _, row in edits.iterrows():
        index = index_by_key[tuple(row[column] for column in MAPPING_KEY)]
        result.at[index, "value"] = row["reviewed_value"]
        result.at[index, "value_code"] = row["reviewed_code"]
        result.at[index, "mapping_status"] = "MAPPED"
        result.at[index, "mapping_reason"] = "REVIEW_EDIT_VALIDATED_TAXONOMY"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output_path, index=False, encoding="utf-8-sig")
    report = {
        "mapping_rows": len(result),
        "review_rows": len(review),
        "applied_edit_rows": len(edits),
        "uncertain_rows_preserved": int(review["review_decision"].eq("UNCERTAIN").sum()),
        "blank_decision_rows_preserved": int(review["review_decision"].eq("").sum()),
        "status_counts": {
            str(key): int(value)
            for key, value in result["mapping_status"].value_counts().items()
        },
        "policy": "Only taxonomy-validated EDIT rows are applied; UNCERTAIN and blank review decisions preserve source status.",
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {key: int(value) for key, value in report.items() if isinstance(value, int)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply reviewed product Facet mapping edits")
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--taxonomy", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            apply(
                mapping_path=args.mapping,
                review_path=args.review,
                taxonomy_path=args.taxonomy,
                output_path=args.output,
                report_path=args.report,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
