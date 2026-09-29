"""Validation and normalization for the product evidence input contract.

This module deliberately does not manufacture product rows.  It accepts an
export from the real product/category/evidence sources and fails closed when
identity or provenance fields are missing.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

REQUIRED_COLUMNS = (
    "catalog_id",
    "source_product_id",
    "category_id",
    "category_name",
    "name",
    "source_document_id",
    "license_status",
)
OPTIONAL_COLUMNS = (
    "description",
    "spec_summary",
    "product_form",
    "functional_ingredients",
    "intake_method",
    "source_row_id",
    "source_text",
    "source_review_id",
    "source_keyword",
)


class CanonicalProductError(ValueError):
    """Raised when a canonical product export cannot be trusted."""


def load_canonical_product_evidence(path: Path) -> pd.DataFrame:
    """Read and validate a CSV/Parquet canonical product evidence export."""
    if not path.exists():
        raise FileNotFoundError(f"canonical product evidence not found: {path}")
    frame = pd.read_parquet(path) if path.suffix.lower() == ".parquet" else pd.read_csv(path, dtype=str)
    frame = frame.fillna("")
    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise CanonicalProductError("missing required canonical columns: " + ", ".join(missing))
    for column in (*REQUIRED_COLUMNS, *OPTIONAL_COLUMNS):
        if column not in frame.columns:
            frame[column] = ""
        frame[column] = frame[column].astype(str).str.strip()
    if frame.empty:
        raise CanonicalProductError("canonical product evidence is empty")
    for column in REQUIRED_COLUMNS:
        if frame[column].eq("").any():
            count = int(frame[column].eq("").sum())
            raise CanonicalProductError(f"canonical column {column!r} has {count} empty rows")

    identity = frame.groupby("catalog_id", sort=False)[["source_product_id", "category_id", "name"]].nunique()
    conflicting = identity[(identity > 1).any(axis=1)]
    if not conflicting.empty:
        ids = ", ".join(map(str, conflicting.index[:10]))
        raise CanonicalProductError(f"conflicting product identity for catalog_id: {ids}")
    return frame
