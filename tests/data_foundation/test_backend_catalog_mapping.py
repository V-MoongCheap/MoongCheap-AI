import pandas as pd
import pytest

from scripts.data.build_backend_catalog_mapping import build_mapping


def _backend(names: list[str]) -> pd.DataFrame:
    return pd.DataFrame({
        "id": [str(index + 1990) for index in range(len(names))],
        "name": names,
        "spec_summary": [""] * len(names),
        "list_price": [""] * len(names),
        "thumbnail_url": [""] * len(names),
        "description": [""] * len(names),
        "status": ["ACTIVE"] * len(names),
        "created_at": [""] * len(names),
        "updated_at": [""] * len(names),
    })


def _seed(names: list[str]) -> pd.DataFrame:
    return pd.DataFrame({
        "catalog_seed_id": [f"seed-{index}" for index in range(len(names))],
        "source_product_id": [str(index) for index in range(len(names))],
        "name": names,
        "category_id": [f"cat-{index}" for index in range(len(names))],
        "source_category_id": [f"source-cat-{index}" for index in range(len(names))],
    })


def test_mapping_uses_backend_ids_and_preserves_category_key() -> None:
    result, report = build_mapping(_backend([" A  상품 ", "B 상품"]), _seed(["A 상품", "B 상품"]))
    assert result["catalog_id"].tolist() == ["1990", "1991"]
    assert result["category_key"].tolist() == ["cat-0", "cat-1"]
    assert report["category_id_available"] is False


def test_mapping_rejects_duplicate_names() -> None:
    with pytest.raises(ValueError, match="duplicate names"):
        build_mapping(_backend(["A", "A"]), _seed(["A", "B"]))


def test_mapping_rejects_unmatched_catalog() -> None:
    with pytest.raises(ValueError, match="catalog mismatch"):
        build_mapping(_backend(["A", "B"]), _seed(["A", "C"]))
