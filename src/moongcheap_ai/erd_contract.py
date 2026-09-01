"""Validation helpers for the Backend ERD handoff boundary."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd


def _result(errors: list[str], warnings: list[str]) -> dict[str, Any]:
    return {"status": "INVALID" if errors else "VALID", "errors": errors, "warnings": warnings}


def validate_category_seed(frame: pd.DataFrame) -> dict[str, Any]:
    required = {"category_key", "parent_key", "name", "depth", "facet"}
    errors = [f"missing columns: {sorted(required - set(frame.columns))}"] if required - set(frame.columns) else []
    warnings: list[str] = []
    if errors:
        return _result(errors, warnings)
    keys = frame["category_key"].astype(str)
    if keys.duplicated().any():
        errors.append("duplicate category_key")
    known = set(keys)
    for _, row in frame.iterrows():
        key, parent = str(row["category_key"]), str(row["parent_key"] or "")
        if parent and parent not in known:
            errors.append(f"unknown parent_key: {parent}")
        try:
            depth = int(row["depth"])
            if depth < 1:
                errors.append(f"invalid depth: {key}")
        except (TypeError, ValueError):
            errors.append(f"invalid depth: {key}")
        facet = str(row["facet"] or "").strip()
        if facet:
            try:
                parsed = json.loads(facet)
                if not isinstance(parsed, dict):
                    errors.append(f"facet must be a JSON object: {key}")
            except json.JSONDecodeError:
                errors.append(f"invalid facet JSON: {key}")
    return _result(sorted(set(errors)), warnings)


def validate_catalog_export(frame: pd.DataFrame, category_keys: set[str] | None = None) -> dict[str, Any]:
    id_present = "id" in frame.columns or "catalog_seed_id" in frame.columns
    errors = [] if id_present else ["catalog export needs id or catalog_seed_id"]
    errors.extend(["catalog export needs category_id"] if "category_id" not in frame.columns else [])
    warnings: list[str] = []
    if "category_id" in frame.columns:
        empty = frame["category_id"].isna() | frame["category_id"].astype(str).str.strip().eq("")
        if empty.any():
            errors.append(f"empty category_id rows: {int(empty.sum())}")
        if category_keys:
            unknown = set(frame.loc[~empty, "category_id"].astype(str)) - category_keys
            if unknown:
                warnings.append(f"category_id values not present in seed keys: {len(unknown)}")
    return _result(sorted(set(errors)), warnings)


def validate_labeled_demands(frame: pd.DataFrame) -> dict[str, Any]:
    required = {"demand_id", "catalog_id", "label", "facet_values"}
    errors = [f"missing columns: {sorted(required - set(frame.columns))}"] if required - set(frame.columns) else []
    warnings: list[str] = []
    if errors:
        return _result(errors, warnings)
    for index, raw in enumerate(frame["facet_values"].fillna("")):
        try:
            if not isinstance(json.loads(str(raw)), dict):
                errors.append(f"facet_values must be object at row {index}")
        except json.JSONDecodeError:
            errors.append(f"invalid facet_values JSON at row {index}")
    return _result(sorted(set(errors)), warnings)
