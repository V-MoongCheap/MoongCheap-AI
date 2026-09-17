from __future__ import annotations

import json
from pathlib import Path

from moongcheap_ai.data_foundation.labeling import TaxonomyLoader
from moongcheap_ai.data_foundation.product_facet_mapping import build_product_mapping, load_taxonomy


ROOT = Path(__file__).resolve().parents[2]


def test_deprecated_vitamin_d_code_resolves_to_canonical_code() -> None:
    taxonomy = json.loads((ROOT / "config/facet_taxonomy_v2_2.json").read_text(encoding="utf-8"))
    loader = TaxonomyLoader(taxonomy)

    values, warnings = loader.resolve("health-functional-food:vitamin_mineral", "비타민D")

    assert not warnings
    assert values["functional_ingredients"]["code"] == 2
    assert values["functional_ingredients"]["value"] == "비타민 D"


def test_deprecated_vitamin_d_code_is_not_used_for_new_product_mapping() -> None:
    taxonomy = load_taxonomy(ROOT / "config/facet_taxonomy_v2_2.json")
    catalog = __import__("pandas").DataFrame([{
        "catalog_id": "catalog-1",
        "source_product_id": "product-1",
        "category_id": "health-functional-food:vitamin_mineral",
        "name": "비타민D 1000",
        "title": "비타민D 1000",
        "keywords_json": "",
    }])

    mapping = build_product_mapping(catalog, taxonomy)
    row = mapping[mapping["facet_name"].eq("functional_ingredients")].iloc[0]

    assert row["mapping_status"] == "MAPPED"
    assert int(row["value_code"]) == 2
    assert row["value"] == "비타민 D"


def test_product_display_values_resolve_to_ingredient_canonical_values() -> None:
    taxonomy = json.loads((ROOT / "config/facet_taxonomy_v2_2.json").read_text(encoding="utf-8"))
    loader = TaxonomyLoader(taxonomy)

    for category_id, text, expected_code, expected_value in (
        ("health-functional-food:red_ginseng", "홍삼제품", 1, "홍삼"),
        ("health-functional-food:probiotics", "프로바이오틱스 제품", 1, "프로바이오틱스"),
    ):
        values, warnings = loader.resolve(category_id, text)
        assert not warnings
        assert values["functional_ingredients"]["code"] == expected_code
        assert values["functional_ingredients"]["value"] == expected_value
