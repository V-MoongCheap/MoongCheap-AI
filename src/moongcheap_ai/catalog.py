from __future__ import annotations

import html
import re
import unicodedata
from collections import defaultdict
from typing import Any

import pandas as pd


def normalize_name(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[\u0000-\u001f\u007f\u200b\u200c\u200d\ufeff]", "", text)
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip()


def normalize_barcode(value: Any) -> str:
    return re.sub(r"[\s-]", "", str(value or "").strip())


def barcode_valid(value: str) -> bool:
    return bool(re.fullmatch(r"\d{8,14}", value))


def source_category_path_from_file(source_file: str) -> str:
    """Recover AI-Hub hierarchy lost by the COCO category name."""
    parts = [part for part in re.split(r"[\\\\/]", str(source_file)) if part]
    try:
        start = next(index for index, part in enumerate(parts) if part.lower() == "logistics_product") + 1
    except StopIteration:
        return ""
    folders = parts[start:-2]
    if folders and re.match(r"^02_", folders[0]) and len(folders) > 1:
        folders = folders[1:]
    category_parts = [part for part in folders if re.match(r"^\d{2}_", part)][:2]
    return " > ".join(category_parts)


ALIASES = {
    "product_name_raw": ["product_name", "productname", "상품명", "품명", "name", "제품명"],
    "barcode": ["barcode", "바코드", "ean", "upc"],
    "kan_code": ["kan_code", "kancode", "kan", "분류코드", "상품분류코드"],
    "source_category_id": ["source_category_id", "category_id", "카테고리id"],
    "source_category_name": ["source_category_name", "product_category", "category_name", "카테고리명"],
    "source_category_path": ["source_category_path", "category_path", "카테고리경로"],
    "manufacturer": ["manufacturer", "제조사", "제조업체"],
    "brand": ["brand", "브랜드"],
    "image_url": ["image", "image_url", "이미지", "상품이미지", "사진"],
}


def pick_column(columns: list[str], candidates: list[str]) -> str | None:
    normalized = {re.sub(r"[^a-z0-9가-힣]", "", c.lower()): c for c in columns}
    for candidate in candidates:
        key = re.sub(r"[^a-z0-9가-힣]", "", candidate.lower())
        if key in normalized:
            return normalized[key]
    return None


def source_rows_to_staging(frame: pd.DataFrame, source: str, source_file: str) -> pd.DataFrame:
    columns = [str(c) for c in frame.columns]
    selected = {field: pick_column(columns, candidates) for field, candidates in ALIASES.items()}
    rows = []
    file_category_path = source_category_path_from_file(source_file)
    for index, row in frame.iterrows():
        name = str(row.get(selected["product_name_raw"], "") or "") if selected["product_name_raw"] else ""
        barcode_raw = str(row.get(selected["barcode"], "") or "") if selected["barcode"] else ""
        rows.append({
            "source": source, "source_product_id": barcode_raw, "barcode": normalize_barcode(barcode_raw),
            "barcode_valid": barcode_valid(normalize_barcode(barcode_raw)),
            "product_name_raw": name, "product_name_normalized": normalize_name(name),
            "manufacturer": str(row.get(selected["manufacturer"], "") or "") if selected["manufacturer"] else "",
            "brand": str(row.get(selected["brand"], "") or "") if selected["brand"] else "",
            "model_code": "", "quantity_text": "", "capacity_text": "", "package_text": "",
            "source_category_id": str(row.get(selected["source_category_id"], "") or "") if selected["source_category_id"] else "",
            "source_category_name": str(row.get(selected["source_category_name"], "") or "") if selected["source_category_name"] else "",
            "source_category_path": file_category_path or (str(row.get(selected["source_category_path"], "") or "") if selected["source_category_path"] else ""),
            "kan_code": str(row.get(selected["kan_code"], "") or "") if selected["kan_code"] else "",
            "description_raw": "", "spec_raw": "",
            "image_url": str(row.get(selected["image_url"], "") or "") if selected["image_url"] else "",
            "price_raw": "", "source_file": source_file, "source_row": int(index) + 2,
            "length": str(row.get("length", "") or "") if "length" in frame.columns else "",
            "width": str(row.get("width", "") or "") if "width" in frame.columns else "",
            "height": str(row.get("height", "") or "") if "height" in frame.columns else "",
            "weight": str(row.get("weight", "") or "") if "weight" in frame.columns else "",
            "fragile": str(row.get("fragile", "") or "") if "fragile" in frame.columns else "",
            "refrigerate": str(row.get("refrigerate", "") or "") if "refrigerate" in frame.columns else "",
        })
    return pd.DataFrame(rows)


def resolve_identity(staging: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if staging.empty:
        return staging.assign(catalog_seed_id=pd.Series(dtype=str)), pd.DataFrame()
    frame = staging.copy()
    groups: dict[int, str] = {}
    conflicts: list[dict[str, str]] = []
    next_id = 1
    barcode_groups: defaultdict[str, list[int]] = defaultdict(list)
    for index, row in frame.iterrows():
        if row.get("barcode") and bool(row.get("barcode_valid")):
            barcode_groups[str(row["barcode"])].append(index)
    for indexes in barcode_groups.values():
        names = {str(frame.loc[i, "product_name_normalized"]) for i in indexes}
        kans = {str(frame.loc[i, "kan_code"]) for i in indexes if frame.loc[i, "kan_code"]}
        seed = f"catalog-{next_id:06d}"; next_id += 1
        for i in indexes: groups[i] = seed
        if len(names) > 1 or len(kans) > 1:
            conflicts.append({"barcode": str(frame.loc[indexes[0], "barcode"]), "product_names": "|".join(sorted(names)), "kan_codes": "|".join(sorted(kans)), "conflict_type": "same_barcode_different_metadata"})
    for index in frame.index:
        if index not in groups:
            groups[index] = f"catalog-{next_id:06d}"; next_id += 1
    frame["catalog_seed_id"] = [groups[i] for i in frame.index]
    return frame, pd.DataFrame(conflicts)


def build_catalog(resolved: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if resolved.empty:
        return pd.DataFrame(), pd.DataFrame()
    rows, provenance = [], []
    for catalog_id, group in resolved.groupby("catalog_seed_id", sort=True):
        first = group.iloc[0]
        rows.append({"catalog_seed_id": catalog_id, "name": next((x for x in group["product_name_normalized"] if x), ""), "category_key": first.get("source_category_path", ""), "kan_code": next((x for x in group["kan_code"] if x), ""), "barcode": next((x for x in group["barcode"] if x), ""), "manufacturer": next((x for x in group["manufacturer"] if x), ""), "brand": next((x for x in group["brand"] if x), ""), "model_code": "", "capacity_text": "", "package_text": "", "spec_summary": "", "description": "", "thumbnail_url": next((x for x in group["image_url"] if x), ""), "list_price": "", "status": "ACTIVE", "primary_source": first["source"], "source_count": len(group)})
        provenance.extend(group[["source", "source_product_id", "barcode", "kan_code", "source_category_id", "source_file", "source_row"]].assign(catalog_seed_id=catalog_id).to_dict("records"))
    return pd.DataFrame(rows), pd.DataFrame(provenance)
