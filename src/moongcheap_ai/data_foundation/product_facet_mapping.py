"""Evidence-grounded mapping from catalog seeds to the approved facet taxonomy.

The Domeggook catalog and MFDS product registry have different identifiers. This
module therefore joins them only through a conservative category crosswalk and
keeps the observed source fields on every output row.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

import pandas as pd


def _text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if bool(pd.isna(value)):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _norm(value: Any) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", _text(value)).casefold())


CATEGORY_ALIASES: dict[str, tuple[str, ...]] = {
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
GENERIC_FACET_VALUES = {"기타", "정", "환"}


def load_taxonomy(path: str | Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return {str(item["category_id"]): item for item in payload.get("categories", [])}


def map_category(value: Any, taxonomy: dict[str, dict[str, Any]]) -> tuple[str, str, str]:
    text = _norm(value)
    if not text:
        return "", "UNMATCHED", "empty category"
    exact = [key for key, item in taxonomy.items() if _norm(item.get("category_name")) == text]
    if len(exact) == 1:
        return exact[0], "EXACT", "taxonomy category exact match"
    candidates = {
        key for key, aliases in CATEGORY_ALIASES.items()
        if any(_norm(alias) in text for alias in aliases)
    }
    matches = [key for key in taxonomy if key.rsplit(":", 1)[-1] in candidates]
    if len(matches) == 1:
        return matches[0], "ALIAS", "conservative category alias"
    return "", "UNMATCHED", "no unique category mapping"


def _facet_values(category: dict[str, Any], facet_name: str) -> list[dict[str, Any]]:
    for facet in category.get("facets", []):
        if facet.get("name") == facet_name:
            return [
                value
                for value in facet.get("values", [])
                if int(value.get("code", -1)) != 0
                and str(value.get("status", "")).upper() != "DEPRECATED"
            ]
    return []


def build_category_evidence(
    mfds: pd.DataFrame,
    taxonomy: dict[str, dict[str, Any]],
    min_documents: int = 3,
    min_ratio: float = 0.05,
) -> pd.DataFrame:
    fields = {
        "product_form": "product_form",
        "product_type": "product_type",
        "intake_method": "intake_method",
        "storage_method": "storage_method",
        "functional_ingredients": "functional_ingredients",
        "main_functionality": "main_functionality",
    }
    rows: list[dict[str, Any]] = []
    mapped = mfds.copy().fillna("")
    category_values = mapped.apply(
        lambda row: map_category(row.get("raw_category_name") or row.get("product_type"), taxonomy), axis=1
    )
    mapped[["category_id", "category_mapping_status", "category_mapping_reason"]] = pd.DataFrame(
        category_values.tolist(), index=mapped.index
    )
    for category_id, group in mapped[mapped["category_id"].ne("")].groupby("category_id", sort=True):
        category_name = _text(taxonomy[category_id].get("category_name"))
        denominator = int(group["source_product_id"].nunique())
        for source_field, column in fields.items():
            if column not in group:
                continue
            values = group[["source_product_id", column]].copy()
            values["normalized_value"] = values[column].map(_text).map(lambda value: re.sub(r"\s+", " ", value))
            values = values[values["normalized_value"].ne("")]
            for value, value_group in values.groupby("normalized_value", sort=True):
                count = int(value_group["source_product_id"].nunique())
                rows.append({
                    "category_id": category_id,
                    "category_name": category_name,
                    "source": "MFDS_I0030",
                    "source_field": source_field,
                    "normalized_value": value,
                    "document_count": count,
                    "document_ratio": count / denominator if denominator else 0.0,
                    "evidence_product_ids": json.dumps(sorted(value_group["source_product_id"].astype(str).unique().tolist()), ensure_ascii=False),
                    "evidence_status": "CANDIDATE" if count >= min_documents and (count / denominator if denominator else 0.0) >= min_ratio else "LOW_SUPPORT",
                    "mapping_status": "CATEGORY_CROSSWALK",
                })
    return pd.DataFrame(rows)


def build_reference_evidence(
    references: pd.DataFrame, taxonomy: dict[str, dict[str, Any]]
) -> pd.DataFrame:
    """Preserve I2710 official references without assigning them to a catalog item."""
    rows: list[dict[str, Any]] = []
    for index, reference in references.fillna("").iterrows():
        reference_name = _text(reference.get("category_reference_name"))
        ingredient = _text(reference.get("ingredient_name"))
        functionality = _text(reference.get("main_functionality"))
        category_id, status, reason = map_category(
            " | ".join(value for value in (reference_name, ingredient, functionality) if value),
            taxonomy,
        )
        rows.append({
            "reference_id": f"MFDS_I2710:{index + 1}",
            "category_id": category_id,
            "category_name": _text(taxonomy.get(category_id, {}).get("category_name")),
            "category_mapping_status": status,
            "category_mapping_reason": reason,
            "reference_name": reference_name,
            "ingredient_name": ingredient,
            "main_functionality": functionality,
            "daily_intake_min": _text(reference.get("daily_intake_min")),
            "daily_intake_max": _text(reference.get("daily_intake_max")),
            "unit": _text(reference.get("unit")),
            "caution": _text(reference.get("caution")),
            "source": "MFDS_I2710",
            "evidence_scope": "OFFICIAL_REFERENCE_NOT_CATALOG_FACT",
        })
    return pd.DataFrame(rows)


def build_product_mapping(catalog: pd.DataFrame, taxonomy: dict[str, dict[str, Any]]) -> pd.DataFrame:
    text_columns = [
        "name", "title", "keywords_json", "package_spec", "ingredients_raw",
        "nutrition_raw", "functionality_raw", "intake_raw", "caution_raw", "expiry_storage_raw",
    ]
    rows: list[dict[str, Any]] = []
    for _, product in catalog.fillna("").sort_values("catalog_id").iterrows():
        category_id = _text(product.get("category_id"))
        category = taxonomy.get(category_id)
        if category is None:
            for facet_name in ("product_form", "functional_ingredients", "daily_frequency"):
                rows.append(_mapping_row(product, category_id, facet_name, None, "UNMATCHED_CATEGORY", ""))
            continue
        text_parts = [(column, _text(product.get(column))) for column in text_columns]
        combined = _norm(" ".join(value for _, value in text_parts))
        for facet_name in ("product_form", "functional_ingredients", "daily_frequency"):
            candidates: list[tuple[dict[str, Any], list[str], list[str]]] = []
            for value in _facet_values(category, facet_name):
                aliases = [_text(alias) for alias in value.get("aliases", [])]
                terms = [_text(value.get("value")), *aliases]
                # Generic one-character forms and "other" are too ambiguous in
                # seller titles/categories to serve as automatic product facts.
                terms = [term for term in terms if _norm(term) not in GENERIC_FACET_VALUES and len(_norm(term)) > 1]
                hits = [term for term in terms if term and _norm(term) in combined]
                if hits:
                    source_fields = sorted({
                        column
                        for column, raw in text_parts
                        if any(_norm(hit) in _norm(raw) for hit in hits)
                    })
                    candidates.append((value, hits, source_fields))
            candidate_evidence = [
                {
                    "value_code": int(value["code"]),
                    "value": _text(value.get("value")),
                    "matched_terms": hits,
                    "source_fields": source_fields,
                }
                for value, hits, source_fields in candidates
            ]
            if len(candidates) == 1:
                value, hits, source_fields = candidates[0]
                rows.append(_mapping_row(
                    product, category_id, facet_name, value, "MAPPED", hits[0],
                    source_fields, "OBSERVED_CATALOG_TEXT", candidate_evidence,
                ))
            elif len(candidates) > 1:
                rows.append(_mapping_row(
                    product, category_id, facet_name, None, "AMBIGUOUS",
                    ";".join(hit for _, hits, _ in candidates for hit in hits),
                    None, "MULTIPLE_OBSERVED_VALUES", candidate_evidence,
                ))
            else:
                rows.append(_mapping_row(product, category_id, facet_name, None, "UNKNOWN", "", None, "NO_OBSERVED_VALUE"))
    return pd.DataFrame(rows)


def _mapping_row(product: pd.Series, category_id: str, facet_name: str, value: dict[str, Any] | None,
                 status: str, matched_text: str, source_fields: list[str] | None = None,
                 reason: str = "", candidate_evidence: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "catalog_id": _text(product.get("catalog_id")),
        "source_product_id": _text(product.get("source_product_id")),
        "category_id": category_id,
        "facet_name": facet_name,
        "value_code": "" if value is None else int(value["code"]),
        "value": "" if value is None else _text(value.get("value")),
        "mapping_status": status,
        "mapping_reason": reason,
        "matched_text": matched_text,
        "source_fields": json.dumps(source_fields or [], ensure_ascii=False),
        "candidate_evidence": json.dumps(candidate_evidence or [], ensure_ascii=False),
        "source_document_id": _text(product.get("source_document_id")),
        "source": _text(product.get("source")),
        "license_status": _text(product.get("license_status")),
    }
