import pandas as pd
import pytest

from moongcheap_ai.data_foundation.canonical_product import CanonicalProductError, load_canonical_product_evidence


def _row(**overrides):
    row = {
        "catalog_id": "catalog-1",
        "source_product_id": "mfds-1",
        "category_id": "category-1",
        "category_name": "프로바이오틱스",
        "name": "실제 상품",
        "source_document_id": "doc-1",
        "license_status": "LOCAL_ONLY",
    }
    row.update(overrides)
    return row


def test_canonical_product_loader_adds_optional_provenance_columns(tmp_path):
    path = tmp_path / "products.csv"
    pd.DataFrame([_row(source_review_id="review-1", source_keyword="유산균")]).to_csv(path, index=False)

    result = load_canonical_product_evidence(path)

    assert result.loc[0, "source_review_id"] == "review-1"
    assert "source_text" in result


def test_canonical_product_loader_rejects_missing_identity(tmp_path):
    path = tmp_path / "products.csv"
    pd.DataFrame([_row(name="")]).to_csv(path, index=False)

    with pytest.raises(CanonicalProductError, match="name"):
        load_canonical_product_evidence(path)


def test_canonical_product_loader_rejects_conflicting_rows(tmp_path):
    path = tmp_path / "products.csv"
    pd.DataFrame([_row(name="상품 A"), _row(name="상품 B")]).to_csv(path, index=False)

    with pytest.raises(CanonicalProductError, match="conflicting"):
        load_canonical_product_evidence(path)
