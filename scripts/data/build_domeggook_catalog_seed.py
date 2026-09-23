"""Build a health Catalog seed from observed Domeggook seller offers.

This is a local, provisional catalog. It preserves the seller item ID and
does not infer missing product facts. Category mapping is intentionally
conservative and emits review status for non-exact matches.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pandas as pd


TAXONOMY_ALIASES = {
    "blood_sugar_metabolic": ("혈당", "혈당관리"),
    "dietary_fiber": ("식이섬유", "체중관리", "다이어트"),
    "eye_health": ("루테인", "눈건강", "눈 건강"),
    "heart_blood": ("혈행", "혈압"),
    "joint_health": ("관절", "연골"),
    "liver_health": ("밀크씨슬", "간건강", "간 건강"),
    "male_health": ("남성건강", "남성 건강"),
    "omega_fatty_acid": ("오메가3", "오메가 3", "오메가-3", "오메가"),
    "other_functional": ("기타건강보조식품", "건강보조"),
    "probiotics": ("프로바이오틱스", "유산균", "프리바이오틱스"),
    "propolis": ("프로폴리스",),
    "protein": ("단백질", "프로틴"),
    "red_ginseng": ("홍삼", "인삼"),
    "skin_collagen": ("콜라겐", "피부"),
    "theanine_sleep": ("테아닌", "수면"),
    "vitamin_mineral": ("비타민", "미네랄"),
}


def _norm(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "").casefold())


def _taxonomy(path: Path) -> dict[str, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        str(item["category_id"]).rsplit(":", 1)[-1]: str(item.get("category_name", ""))
        for item in payload.get("categories", [])
    }


def _map_category(raw: object, taxonomy: dict[str, str]) -> tuple[str, str, str]:
    text = _norm(raw)
    if not text:
        return "", "UNMATCHED", "empty seller category"
    exact = [key for key, name in taxonomy.items() if _norm(name) == text]
    if len(exact) == 1:
        return f"health-functional-food:{exact[0]}", "EXACT", "taxonomy name exact match"
    candidates = [key for key, aliases in TAXONOMY_ALIASES.items() if any(_norm(alias) in text for alias in aliases)]
    if len(candidates) == 1 and candidates[0] in taxonomy:
        return f"health-functional-food:{candidates[0]}", "ALIAS", "conservative seller-category alias"
    return "", "UNMATCHED", "no unique taxonomy mapping"


def build(offers_path: Path, taxonomy_path: Path, output_dir: Path) -> dict[str, object]:
    offers = pd.read_csv(offers_path, dtype=str, encoding="utf-8-sig").fillna("")
    required = {"item_id", "title", "category", "seller_id", "status"}
    missing = sorted(required - set(offers.columns))
    if missing:
        raise ValueError("seller offers missing columns: " + ", ".join(missing))
    offers = offers.drop_duplicates("item_id", keep="first").copy()
    taxonomy = _taxonomy(taxonomy_path)
    mapped = offers["category"].map(lambda value: _map_category(value, taxonomy))
    offers[["category_id", "category_mapping_status", "category_mapping_reason"]] = pd.DataFrame(mapped.tolist(), index=offers.index)
    offers["catalog_id"] = "catalog-seed-domeggook-" + offers["item_id"].astype(str).str.strip()
    offers["source_product_id"] = offers["item_id"].astype(str).str.strip()
    offers["name"] = offers["detail_product_name"].where(offers.get("detail_product_name", "").ne(""), offers["title"]) if "detail_product_name" in offers else offers["title"]
    offers["category_name"] = offers["category_id"].map(lambda value: taxonomy.get(str(value).rsplit(":", 1)[-1], "") if value else "")
    offers["source"] = "DOMEGGOOK"
    offers["source_document_id"] = offers["item_id"].astype(str)
    offers["source_text"] = offers["semantic_text"] if "semantic_text" in offers else offers["title"]
    offers["license_status"] = "LOCAL_ONLY"
    catalog_columns = [
        "catalog_id", "source_product_id", "category_id", "category_name", "name",
        "title", "category", "seller_id", "status", "base_unit_price", "min_unit_price",
        "moq", "loq", "order_unit", "inventory_raw", "delivery_method", "delivery_pay",
        "delivery_fee_raw", "package_spec", "ingredients_raw", "nutrition_raw",
        "functionality_raw", "intake_raw", "caution_raw", "expiry_storage_raw", "keywords_json",
        "source", "source_document_id", "source_text", "license_status",
        "category_mapping_status", "category_mapping_reason",
    ]
    catalog = offers[[column for column in catalog_columns if column in offers.columns]].sort_values("catalog_id")
    mapping = catalog[["catalog_id", "source_product_id", "category", "category_id", "category_mapping_status", "category_mapping_reason"]]
    output_dir.mkdir(parents=True, exist_ok=True)
    catalog.to_csv(output_dir / "catalog_seed.csv", index=False, encoding="utf-8-sig")
    mapping.to_csv(output_dir / "category_mapping_candidates.csv", index=False, encoding="utf-8-sig")
    return {
        "rows": len(catalog),
        "unique_catalog_ids": int(catalog.catalog_id.nunique()),
        "mapping_status": catalog.category_mapping_status.value_counts().to_dict(),
        "mapped_categories": int(catalog.category_id.ne("").sum()),
        "output_dir": str(output_dir),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--offers", type=Path, required=True)
    parser.add_argument("--taxonomy", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.offers, args.taxonomy, args.output_dir), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
