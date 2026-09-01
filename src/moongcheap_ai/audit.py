from __future__ import annotations

from typing import Any
from pathlib import Path

import pandas as pd


def _nonempty(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame:
        return pd.Series(False, index=frame.index)
    return frame[column].fillna("").astype(str).str.strip().ne("")


def _unique_count(frame: pd.DataFrame, column: str) -> int:
    values = frame.loc[_nonempty(frame, column), column].astype(str).str.strip()
    return int(values.nunique())


def audit_aihub(staging: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame]:
    """Calculate observed-data quality metrics without inventing categories."""
    frame = staging.copy()
    name_ok = _nonempty(frame, "product_name_normalized")
    barcode_ok = _nonempty(frame, "barcode")
    kan_ok = _nonempty(frame, "kan_code")
    summary: dict[str, Any] = {
        "raw_row_count": int(len(frame)),
        "product_name_non_null": int(name_ok.sum()),
        "barcode_non_null": int(barcode_ok.sum()),
        "barcode_valid_count": int(frame.loc[barcode_ok, "barcode_valid"].fillna(False).astype(bool).sum()) if "barcode_valid" in frame else 0,
        "barcode_invalid_count": int((barcode_ok & ~frame.get("barcode_valid", pd.Series(False, index=frame.index)).fillna(False).astype(bool)).sum()),
        "barcode_valid_ratio_of_non_null": float(frame.loc[barcode_ok, "barcode_valid"].fillna(False).astype(bool).mean()) if "barcode_valid" in frame and barcode_ok.any() else 0.0,
        "kan_code_non_null": int(kan_ok.sum()),
        "unique_barcode_count": _unique_count(frame, "barcode"),
        "unique_product_name_count": _unique_count(frame, "product_name_normalized"),
        "unique_kan_code_count": _unique_count(frame, "kan_code"),
        "duplicate_barcode_occurrences": 0,
        "same_barcode_different_product_name_groups": 0,
        "same_barcode_different_kan_code_groups": 0,
        "category_product_counts": {},
    }
    conflicts: list[dict[str, Any]] = []
    if not frame.empty and "barcode" in frame:
        valid = frame.loc[barcode_ok].copy()
        grouped = valid.groupby("barcode", sort=True, dropna=False)
        summary["duplicate_barcode_occurrences"] = int(sum(max(len(group) - 1, 0) for _, group in grouped))
        for barcode, group in grouped:
            names = sorted(set(group.get("product_name_normalized", pd.Series(dtype=str)).astype(str)))
            kans = sorted(set(group.get("kan_code", pd.Series(dtype=str)).astype(str).replace("", pd.NA).dropna()))
            name_conflict = len(names) > 1
            kan_conflict = len(kans) > 1
            if name_conflict:
                summary["same_barcode_different_product_name_groups"] += 1
            if kan_conflict:
                summary["same_barcode_different_kan_code_groups"] += 1
            if name_conflict or kan_conflict:
                conflicts.append({
                    "barcode": str(barcode),
                    "product_names": "|".join(names),
                    "kan_codes": "|".join(kans),
                    "conflict_type": "same_barcode_different_metadata",
                })
    category_column = "source_category_path" if "source_category_path" in frame else "kan_code"
    if not frame.empty and category_column in frame:
        values = frame.loc[_nonempty(frame, category_column), category_column].astype(str).str.strip()
        summary["category_product_counts"] = {str(k): int(v) for k, v in values.value_counts().sort_index().items()}
    return summary, pd.DataFrame(conflicts, columns=["barcode", "product_names", "kan_codes", "conflict_type"])


def build_category_source_mapping(staging: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "source", "source_category_id", "source_category_name", "source_category_path",
        "category_key", "kan_code", "mapping_method", "mapping_score",
        "review_status", "review_note",
    ]
    if staging.empty:
        return pd.DataFrame(columns=columns)
    rows: list[dict[str, Any]] = []
    keys = ["source", "source_category_id", "source_category_name", "source_category_path", "kan_code"]
    for values, _ in staging.fillna("").groupby(keys, sort=True, dropna=False):
        source, source_id, source_name, source_path, kan_code = values
        if not str(kan_code).strip():
            method, category_key, score = "UNMATCHED", "", 0.0
        else:
            method, category_key, score = "EXACT_CODE", f"KAN:{kan_code}", 1.0
        rows.append({
            "source": source,
            "source_category_id": source_id,
            "source_category_name": source_name,
            "source_category_path": source_path,
            "category_key": category_key,
            "kan_code": kan_code,
            "mapping_method": method,
            "mapping_score": score,
            "review_status": "REVIEW" if method == "UNMATCHED" else "OBSERVED",
            "review_note": "KAN code observed from AI-Hub; official codebook confirmation pending" if method == "EXACT_CODE" else "KAN code is missing",
        })
    return pd.DataFrame(rows, columns=columns)


def product_catalog_coverage(staging: pd.DataFrame, catalog: pd.DataFrame) -> dict[str, Any]:
    row_count = len(staging)
    denominator = row_count or 1
    return {
        "raw_product_rows": int(row_count),
        "unique_barcode_count": _unique_count(staging, "barcode"),
        "unique_product_name_count": _unique_count(staging, "product_name_normalized"),
        "canonical_product_count": int(len(catalog)),
        "kan_category_count": _unique_count(staging, "kan_code"),
        "category_product_counts": {str(k): int(v) for k, v in staging.loc[_nonempty(staging, "kan_code"), "kan_code"].value_counts().sort_index().items()} if "kan_code" in staging else {},
        "barcode_coverage_ratio": round(_nonempty(staging, "barcode").sum() / denominator, 6),
        "kan_coverage_ratio": round(_nonempty(staging, "kan_code").sum() / denominator, 6),
        "image_coverage_ratio": round(_nonempty(staging, "image_url").sum() / denominator, 6),
        "manufacturer_coverage_ratio": round(_nonempty(staging, "manufacturer").sum() / denominator, 6),
        "source_counts": {str(k): int(v) for k, v in staging["source"].value_counts().items()} if "source" in staging else {},
    }


def write_today_result(
    path: Path,
    aihub_audit: dict[str, Any] | None,
    coverage: dict[str, Any] | None,
    mfds_status: dict[str, Any] | None,
    facet_status: dict[str, Any] | None,
    conflict_count: int = 0,
) -> None:
    audit = aihub_audit or {}
    catalog = coverage or {}
    lines = [
        "# AI / Data Pipeline Result",
        "",
        "## AI-Hub Raw",
        "",
        f"- Raw files: {audit.get('raw_file_count', 'N/A')}",
        f"- Raw rows: {audit.get('raw_row_count', 'N/A')}",
        "",
        "## Product Coverage",
        "",
        f"- Raw product rows: {catalog.get('raw_product_rows', 'N/A')}",
        f"- Unique barcode: {catalog.get('unique_barcode_count', 'N/A')}",
        f"- Unique product name: {catalog.get('unique_product_name_count', 'N/A')}",
        f"- Canonical product count: {catalog.get('canonical_product_count', 'N/A')}",
        "",
        "## Barcode Quality",
        "",
        f"- Duplicate barcode occurrences: {audit.get('duplicate_barcode_occurrences', 'N/A')}",
        f"- Same barcode / different name groups: {audit.get('same_barcode_different_product_name_groups', 'N/A')}",
        f"- Same barcode / different KAN groups: {audit.get('same_barcode_different_kan_code_groups', 'N/A')}",
        f"- Identity conflict rows: {conflict_count}",
        "",
        "## KAN Coverage",
        "",
        f"- Unique observed KAN codes: {audit.get('unique_kan_code_count', 'N/A')}",
        f"- KAN coverage ratio: {catalog.get('kan_coverage_ratio', 'N/A')}",
        "- Category master status: observed-only until an official KAN codebook is supplied",
        "",
        "## MFDS / Facet",
        "",
        f"- MFDS: {(mfds_status or {}).get('status', 'NOT_RUN')}",
        f"- Facet: {(facet_status or {}).get('status', 'NOT_RUN')}",
        "- No missing Product Fact or Facet values were fabricated.",
        "",
        "## Backend Schema Problems",
        "",
        "- `thumbnail_url` may need a nullable or placeholder policy.",
        "- Barcode, external product ID, and KAN source mapping need provenance storage.",
        "",
        "## Limitations",
        "",
        "- Product Catalog V1 reflects the supplied AI-Hub data and is not a complete domestic product database.",
        "- MFDS Facet Discovery remains pending until valid I0030/I2710 raw pages or an API key are available.",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
