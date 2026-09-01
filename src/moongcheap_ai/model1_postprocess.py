"""Normalize Model 1 candidates and apply evidence-backed product mapping."""
from __future__ import annotations
import re
import unicodedata
from typing import Any
import pandas as pd
from .category_v2_1 import classify_v2_1

CANONICAL_FACETS = {"form": ("product_form", "제품 형태"), "product form": ("product_form", "제품 형태"), "제품 형태": ("product_form", "제품 형태"), "functional ingredients": ("functional_ingredients", "기능성 성분"), "기능성 성분": ("functional_ingredients", "기능성 성분"), "probiotic strain": ("probiotic_strain", "프로바이오틱스 균주"), "프로바이오틱스 균주": ("probiotic_strain", "프로바이오틱스 균주"), "regulated function": ("regulated_function", "규제 기능"), "규제 기능": ("regulated_function", "규제 기능")}
FORM_VALUES = {"powder": "분말", "분말": "분말", "capsule": "캡슐", "캡슐": "캡슐", "tablet": "정", "정": "정", "liquid": "액상", "액상": "액상"}

def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(value or ""))).strip().casefold()

def canonical_facet(facet_id: Any, name: Any) -> tuple[str, str]:
    return CANONICAL_FACETS.get(normalize_text(facet_id), CANONICAL_FACETS.get(normalize_text(name), (normalize_text(facet_id) or "unknown", str(name or facet_id).strip())))

def canonical_value(facet_id: str, value: Any) -> str:
    value = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(value or ""))).strip()
    return FORM_VALUES.get(value.casefold(), value) if facet_id == "product_form" else value

def atomic_values(facet_id: str, value: Any) -> list[str]:
    cleaned = canonical_value(facet_id, value)
    parts = re.split(r"[,;\n]+", cleaned) if facet_id == "functional_ingredients" else re.split(r"[,;·•\n]+", cleaned) if facet_id == "regulated_function" else [cleaned]
    result = []
    for part in parts:
        part = re.sub(r"^\s*[\[(]?\d+[.)\]]?\s*", "", part).strip(" .")
        if facet_id == "regulated_function":
            part = re.sub(r"\s*\((?:생리활성기능|기능성)?\s*\d+등급\)\s*$", "", part).strip()
        if part and part not in result:
            result.append(part)
    return result

def normalize_candidates(review: pd.DataFrame) -> pd.DataFrame:
    columns = ["category_key", "facet_id", "facet_name", "definition", "value", "aliases", "evidence_product_count", "evidence_product_ids", "source_fields", "status"]
    rows = []
    for _, row in review.fillna("").iterrows():
        facet_id, facet_name = canonical_facet(row.get("facet_id_candidate"), row.get("name"))
        for value in atomic_values(facet_id, row.get("value")):
            rows.append({"category_key": str(row.get("category_key", "")).strip(), "facet_id": facet_id, "facet_name": facet_name, "definition": str(row.get("definition", "")).strip(), "value": value, "alias": str(row.get("alias", "")).strip(), "source_product_id": str(row.get("source_product_id", "")).strip(), "source_field": str(row.get("source_field", "")).strip()})
    if not rows:
        return pd.DataFrame(columns=columns)
    data = pd.DataFrame(rows)
    grouped = []
    for keys, group in data.groupby(["category_key", "facet_id", "facet_name", "value"], sort=True):
        definitions = group.loc[group.definition != "", "definition"]
        grouped.append({"category_key": keys[0], "facet_id": keys[1], "facet_name": keys[2], "definition": definitions.iloc[0] if not definitions.empty else "", "value": keys[3], "aliases": "|".join(sorted({x for x in group.alias if x})), "evidence_product_count": group.source_product_id.nunique(), "evidence_product_ids": "|".join(sorted(set(group.source_product_id))), "source_fields": "|".join(sorted(set(group.source_field))), "status": "PROVISIONAL_NORMALIZED_CANDIDATE"})
    return pd.DataFrame(grouped, columns=columns)

def map_products(products: pd.DataFrame, candidates: pd.DataFrame) -> pd.DataFrame:
    columns = ["source_product_id", "product_name", "category_key", "category_name", "facet_id", "facet_name", "value", "source_field", "mapping_status", "mapping_method"]
    data = products.fillna("").copy()
    classified = data.apply(classify_v2_1, axis=1, result_type="expand")
    data["category_key"] = [f"health-functional-food:{key.lower()}" if row["product_type"] else "UNMAPPED" for (_, row), key in zip(data.iterrows(), classified[0])]
    data["category_name"] = classified[1].values
    rows = []
    for _, product in data.iterrows():
        for (category_key, facet_id, facet_name), group in candidates[candidates.category_key == product.category_key].groupby(["category_key", "facet_id", "facet_name"], sort=True):
            field = {"product_form": "product_form", "functional_ingredients": "functional_ingredients", "probiotic_strain": "functional_ingredients", "regulated_function": "main_functionality"}.get(facet_id, "")
            source = normalize_text(product.get(field, ""))
            matches = sorted({row.value for _, row in group.iterrows() if normalize_text(row.value) in source})
            values = matches or [""]
            for value in values:
                rows.append({"source_product_id": product.get("source_product_id", ""), "product_name": product.get("name", ""), "category_key": category_key, "category_name": product.category_name, "facet_id": facet_id, "facet_name": facet_name, "value": value, "source_field": field, "mapping_status": "MAPPED" if value else "UNMAPPED", "mapping_method": "evidence_substring"})
    return pd.DataFrame(rows, columns=columns)
