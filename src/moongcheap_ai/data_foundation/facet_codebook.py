"""Build versioned facet codebooks and clustering-ready demand vectors."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


def load_codebook(taxonomy_path: Path, taxonomy_version: str = "v2.1") -> pd.DataFrame:
    payload = json.loads(taxonomy_path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for category in payload.get("categories", []):
        category_id = str(category.get("category_id", "")).strip()
        for facet in sorted(category.get("facets", []), key=lambda item: int(item.get("order", 0))):
            facet_name = str(facet.get("name", "")).strip()
            order = int(facet.get("order", 0))
            for value in facet.get("values", []):
                rows.append({
                    "taxonomy_version": taxonomy_version,
                    "category_id": category_id,
                    "facet_order": order,
                    "facet_name": facet_name,
                    "value_code": int(value["code"]),
                    "value": str(value.get("value", "")).strip(),
                    "aliases": "|".join(str(alias).strip() for alias in value.get("aliases", []) if str(alias).strip()),
                })
    result = pd.DataFrame(rows)
    if result.empty:
        raise ValueError("taxonomy contains no facet values")
    return result.sort_values(["category_id", "facet_order", "value_code"]).reset_index(drop=True)


def build_clustering_input(labeled_demands: pd.DataFrame, codebook: pd.DataFrame) -> pd.DataFrame:
    """Flatten structured facet JSON while retaining the canonical label."""
    if "facet_values" not in labeled_demands:
        raise ValueError("labeled demands require facet_values JSON")
    code_lookup = {(row.category_id, row.facet_name, row.value): int(row.value_code) for row in codebook.itertuples()}
    rows: list[dict[str, Any]] = []
    for _, demand in labeled_demands.fillna("").iterrows():
        try:
            facet_values = json.loads(str(demand["facet_values"]))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid facet_values for demand {demand.get('demand_id', '')}") from exc
        category_id = str(demand.get("category_id", "")).strip()
        row = {
            "demand_id": demand.get("demand_id", ""),
            "catalog_id": demand.get("catalog_id", ""),
            "category_id": category_id,
            "facet_label": demand.get("label", ""),
            "is_substitutable": demand.get("is_substitutable", ""),
            "desired_price_min": demand.get("desired_price_min", ""),
            "desired_price_max": demand.get("desired_price_max", ""),
            "quantity": demand.get("quantity", ""),
            "taxonomy_version": codebook[codebook["category_id"] == category_id]["taxonomy_version"].iloc[0] if not codebook[codebook["category_id"] == category_id].empty else "",
        }
        for facet in codebook[codebook["category_id"] == category_id].drop_duplicates("facet_name").itertuples():
            value = facet_values.get(facet.facet_name, {})
            value_text = str(value.get("value", ""))
            code = int(value.get("code", 0))
            expected = code_lookup.get((category_id, facet.facet_name, value_text), code)
            row[f"facet_{facet.facet_order}_{facet.facet_name}_code"] = expected
        rows.append(row)
    return pd.DataFrame(rows)
