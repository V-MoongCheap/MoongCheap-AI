from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def read_coco_json(path: Path) -> pd.DataFrame:
    """Flatten an AI-Hub COCO annotation file into product-like rows.

    AI-Hub stores product identity in annotation attributes rather than in
    top-level tabular columns. One annotation becomes one staging row and
    image/category metadata is retained for downstream provenance.
    """
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict) or not {"images", "annotations"}.issubset(value):
        return pd.DataFrame()

    images = {item.get("id"): item for item in value.get("images", []) if isinstance(item, dict)}
    categories = {item.get("id"): item for item in value.get("categories", []) if isinstance(item, dict)}
    rows: list[dict[str, Any]] = []
    for annotation in value.get("annotations", []):
        if not isinstance(annotation, dict):
            continue
        attributes = annotation.get("attributes") or {}
        if not isinstance(attributes, dict):
            attributes = {}
        image = images.get(annotation.get("image_id"), {})
        category = categories.get(annotation.get("category_id"), {})
        rows.append(
            {
                "product_name": attributes.get("product_name", ""),
                "barcode": attributes.get("barcode", ""),
                "KAN_code": attributes.get("KAN_code", ""),
                "manufacturer": attributes.get("manufacturer", ""),
                "brand": attributes.get("brand", ""),
                "product_category": category.get("name", ""),
                "source_category_id": annotation.get("category_id", ""),
                "source_category_name": category.get("name", ""),
                "source_category_path": category.get("name", ""),
                "image_filename": image.get("file_name", ""),
                "width": attributes.get("width", ""),
                "height": attributes.get("height", ""),
                "length": attributes.get("length", ""),
                "weight": attributes.get("weight", ""),
                "fragile": attributes.get("fragile", ""),
                "refrigerate": attributes.get("refrigerate", ""),
                "source_annotation_id": annotation.get("id", ""),
            }
        )
    return pd.DataFrame(rows)
