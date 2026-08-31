"""Build an ERD-shaped health category seed from observed MFDS rows only."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

import pandas as pd


class CategorySeedError(ValueError):
    pass


def build_health_category_seed(mfds: pd.DataFrame, facet_by_category: dict[str, dict[str, Any]] | None = None) -> pd.DataFrame:
    """Return category rows ready for Backend review/import.

    No health subcategory is invented: names come from observed MFDS
    ``product_type`` values.  Backend ``category.id`` is intentionally not
    generated here; it must remain the database-owned BIGINT.
    """
    if mfds.empty:
        raise CategorySeedError("MFDS source is empty; cannot create health categories")
    if "product_type" not in mfds.columns:
        raise CategorySeedError("MFDS source needs product_type")
    observed = Counter(str(value).strip() for value in mfds["product_type"].fillna("") if str(value).strip())
    if not observed:
        raise CategorySeedError("MFDS source has no observed product_type values")
    facets = facet_by_category or {}
    rows = [{"category_key": "health-functional-food", "parent_key": "", "name": "건강기능식품", "depth": 1,
             "facet": "", "source": "MFDS_SCOPE", "status": "DRAFT"}]
    for product_type, count in sorted(observed.items()):
        key = f"health-functional-food:{product_type}"
        rows.append({"category_key": key, "parent_key": "health-functional-food", "name": product_type,
                     "depth": 2, "facet": json.dumps(facets.get(product_type, {}), ensure_ascii=False),
                     "source": "MFDS_OBSERVED", "observed_count": count, "status": "DRAFT"})
    return pd.DataFrame(rows)


def write_health_category_seed(mfds_path, output_path) -> dict[str, Any]:
    mfds = pd.read_parquet(mfds_path) if str(mfds_path).lower().endswith(".parquet") else pd.read_csv(mfds_path)
    result = build_health_category_seed(mfds)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output_path, index=False, encoding="utf-8-sig")
    return {"status": "COMPLETED", "rows": len(result), "output": str(output_path)}
