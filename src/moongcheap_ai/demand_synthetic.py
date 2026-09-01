"""Deterministic synthetic Demand input generation for pipeline mechanics tests."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

import pandas as pd


REQUIRED_COLUMNS = (
    "demand_id",
    "catalog_id",
    "category_id",
    "extra_requirement",
    "desired_price_min",
    "desired_price_max",
    "quantity",
    "is_substitutable",
    "processed_at",
    "synthetic",
    "source_note",
)

SYNTHETIC_REQUIREMENTS = ("", "조건 없음", "예산 내 추천", "대체 가능한 상품", "세부 조건 확인 필요")


def _values_by_category(taxonomy_path: Path | None) -> dict[str, list[str]]:
    if taxonomy_path is None or not taxonomy_path.exists():
        return {}
    payload = json.loads(taxonomy_path.read_text(encoding="utf-8"))
    result: dict[str, list[str]] = {}
    for category in payload.get("categories", []):
        category_id = str(category.get("category_id", "")).strip()
        values: list[str] = []
        for facet in category.get("facets", []):
            for value in facet.get("values", []):
                if int(value.get("code", 0)) != 0:
                    values.append(str(value.get("value", "")).strip())
        if category_id and values:
            result[category_id] = values
    return result


def prepare_demand_input(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize synthetic or Backend-exported Demand rows before labeling."""
    result = frame.copy()
    for column in REQUIRED_COLUMNS:
        if column not in result:
            result[column] = ""
    text_columns = ["demand_id", "catalog_id", "category_id", "extra_requirement", "processed_at", "source_note"]
    for column in text_columns:
        result[column] = result[column].fillna("").astype(str).str.strip()
    for column in ("desired_price_min", "desired_price_max", "quantity"):
        result[column] = pd.to_numeric(result[column], errors="coerce")
    result["quantity"] = result["quantity"].fillna(1).clip(lower=1).round().astype(int)
    result["desired_price_min"] = result["desired_price_min"].fillna(0).clip(lower=0)
    result["desired_price_max"] = result["desired_price_max"].fillna(result["desired_price_min"])
    result["desired_price_max"] = result[["desired_price_min", "desired_price_max"]].max(axis=1)
    result["is_substitutable"] = result["is_substitutable"].map(
        lambda value: str(value).strip().casefold() not in {"false", "0", "no", "n"}
    )
    result["synthetic"] = True
    return result[list(REQUIRED_COLUMNS)]


def generate_synthetic_demands(
    catalog: pd.DataFrame,
    count: int = 30,
    seed: int = 42,
    taxonomy_path: Path | None = None,
) -> pd.DataFrame:
    """Create clearly marked Demand rows tied to observed catalog IDs only."""
    if catalog.empty:
        raise ValueError("catalog is empty; synthetic demands need catalog rows")
    id_column = "id" if "id" in catalog.columns else "catalog_seed_id" if "catalog_seed_id" in catalog.columns else None
    if id_column is None:
        raise ValueError("catalog needs id or catalog_seed_id")
    rng = random.Random(seed)
    candidates = catalog.fillna("").copy().reset_index(drop=True)
    values_by_category = _values_by_category(taxonomy_path)
    rows: list[dict[str, Any]] = []
    for index in range(count):
        product = candidates.iloc[index % len(candidates)]
        category_id = str(product.get("category_id", "") or product.get("kan_code", "")).strip()
        options = values_by_category.get(category_id, [])
        requirement = rng.choice(options) if options else rng.choice(SYNTHETIC_REQUIREMENTS)
        minimum = rng.choice([10000, 20000, 30000, 50000])
        maximum = minimum + rng.choice([10000, 20000, 30000])
        rows.append({
            "demand_id": f"synthetic-demand-{index + 1:05d}",
            "catalog_id": str(product[id_column]),
            "category_id": category_id,
            "extra_requirement": requirement,
            "desired_price_min": minimum,
            "desired_price_max": maximum,
            "quantity": rng.choice([1, 1, 1, 2, 3]),
            "is_substitutable": rng.choice([True, True, False]),
            "processed_at": "",
            "synthetic": True,
            "source_note": "synthetic mechanics fixture; not a user Demand or product fact",
        })
    return prepare_demand_input(pd.DataFrame(rows))


def generate_from_catalog_file(
    catalog_path: Path,
    output_path: Path,
    count: int = 30,
    seed: int = 42,
    taxonomy_path: Path | None = None,
) -> dict[str, Any]:
    catalog = pd.read_parquet(catalog_path) if catalog_path.suffix.lower() == ".parquet" else pd.read_csv(catalog_path, dtype=str)
    result = generate_synthetic_demands(catalog, count=count, seed=seed, taxonomy_path=taxonomy_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output_path, index=False, encoding="utf-8-sig")
    return {"status": "COMPLETED", "synthetic": True, "rows": len(result), "output": str(output_path), "seed": seed}
