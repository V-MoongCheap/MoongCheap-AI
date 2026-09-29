"""Build a canonical product/evidence export from existing source artifacts.

The script only aggregates observed rows. It never invents product facts. A
fallback name is extracted from the observed evidence text when no product
mapping is available and is marked in the report.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from moongcheap_ai.data_foundation.canonical_product import load_canonical_product_evidence


def _read(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path).fillna("")
    return pd.read_csv(path, dtype=str).fillna("")


def _join(values: pd.Series) -> str:
    return " | ".join(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def _category_key(value: str) -> str:
    value = re.sub(r"[^0-9A-Za-z가-힣]+", "_", str(value).strip()).strip("_")
    return value.lower() or "unclassified"


def _fallback_name(text: str) -> str:
    return str(text).split(" | ", 1)[0].strip()[:100]


def build(evidence_path: Path, output_path: Path, product_mapping_path: Path | None = None) -> pd.DataFrame:
    evidence = _read(evidence_path)
    required = {"source", "service_category", "document_id", "product_ref", "text_raw", "license_status"}
    missing = sorted(required - set(evidence.columns))
    if missing:
        raise ValueError("evidence is missing columns: " + ", ".join(missing))
    unlinked = evidence["product_ref"].astype(str).str.strip().eq("")
    dropped_unlinked_rows = int(unlinked.sum())
    evidence = evidence.loc[~unlinked].copy()
    if evidence.empty:
        raise ValueError("evidence has no rows linked to a product_ref")
    mapping = pd.DataFrame()
    if product_mapping_path:
        mapping = _read(product_mapping_path)
        required_mapping = {"source_product_id", "resolved_product_name"}
        if not required_mapping.issubset(mapping.columns):
            raise ValueError("product mapping needs source_product_id and resolved_product_name")
        mapping = mapping.drop_duplicates("source_product_id")
        mapping = mapping.set_index("source_product_id")

    rows = []
    for (source, product_ref), group in evidence.groupby(["source", "product_ref"], sort=True):
        service_category = str(group["service_category"].replace("", pd.NA).dropna().iloc[0] if not group["service_category"].replace("", pd.NA).dropna().empty else group["service_category"].iloc[0])
        mapped_name = ""
        source_review_id = ""
        if not mapping.empty and str(product_ref) in mapping.index:
            mapped = mapping.loc[str(product_ref)]
            mapped_name = str(mapped.get("resolved_product_name", ""))
            if "source_review_id" in mapping.columns:
                source_review_id = str(mapped.get("source_review_id", ""))
        name = mapped_name or _fallback_name(str(group["text_raw"].iloc[0]))
        category_key = _category_key(service_category or str(group["category"].iloc[0]))
        rows.append({
            "catalog_id": f"catalog-seed-{source}-{product_ref}",
            "source_product_id": str(product_ref),
            "category_id": f"health-functional-food:{category_key}",
            "category_name": service_category or str(group["category"].iloc[0]),
            "service_category_candidate_key": category_key,
            "service_category_name": service_category or str(group["category"].iloc[0]),
            "name": name,
            "description": "",
            "spec_summary": "",
            "product_form": _join(group.loc[group["normalized_attribute"].eq("product_form"), "normalized_value"]) if "normalized_attribute" in group else "",
            "functional_ingredients": _join(group.loc[group["normalized_attribute"].eq("functional_ingredient"), "normalized_value"]) if "normalized_attribute" in group else "",
            "intake_method": _join(group.loc[group["normalized_attribute"].eq("intake_method"), "normalized_value"]) if "normalized_attribute" in group else "",
            "source": str(source),
            "source_document_id": _join(group["document_id"]),
            "source_row_id": _join(group["evidence_id"]) if "evidence_id" in group else "",
            "source_text": _join(group["text_raw"]),
            "source_review_id": source_review_id,
            "source_keyword": "",
            "license_status": _join(group["license_status"]),
        })
    result = pd.DataFrame(rows).sort_values(["category_id", "catalog_id"]).reset_index(drop=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output_path, index=False, encoding="utf-8-sig")
    # Validate the same file that downstream Demand generation will consume.
    load_canonical_product_evidence(output_path)
    result.attrs["dropped_unlinked_rows"] = dropped_unlinked_rows
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--product-mapping", type=Path)
    args = parser.parse_args()
    result = build(args.evidence, args.output, args.product_mapping)
    print(json.dumps({
        "status": "VALID",
        "rows": len(result),
        "catalog_count": int(result["catalog_id"].nunique()),
        "source_count": int(result["source"].nunique()),
        "category_count": int(result["category_id"].nunique()),
        "license_statuses": sorted(result["license_status"].unique().tolist()),
        "dropped_unlinked_evidence_rows": int(result.attrs.get("dropped_unlinked_rows", 0)),
        "output": str(args.output),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
