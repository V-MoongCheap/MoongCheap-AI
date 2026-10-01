import pandas as pd

from moongcheap_ai.data_foundation.demand_label_comparison import (
    compare_labeling_methods,
)
from moongcheap_ai.data_foundation.labeling import TaxonomyLoader


class _FakeLabeler:
    call_count = 0

    def classify(self, rows, loader):
        type(self).call_count += 1
        return {str(row["demand_id"]): {"form": {"code": 1}} for row in rows}


def test_comparison_accepts_evaluation_rows_without_operational_fields():
    loader = TaxonomyLoader(
        {
            "categories": [
                {
                    "category_id": "c1",
                    "facets": [
                        {
                            "name": "form",
                            "order": 1,
                            "values": [
                                {"code": 0, "value": "ALL"},
                                {"code": 1, "value": "분말"},
                            ],
                        }
                    ],
                }
            ],
        }
    )
    demands = pd.DataFrame(
        [
            {
                "demand_id": "d1",
                "catalog_id": "catalog-1",
                "category_id": "c1",
                "extra_requirement": "분말",
            }
        ]
    )

    result, summary = compare_labeling_methods(
        demands,
        loader,
        {
            "catalog-1": [
                {
                    "category_id": "c1",
                    "facet_name": "form",
                    "mapping_status": "MAPPED",
                    "value": "분말",
                }
            ]
        },
        _FakeLabeler(),
        batch_size=1,
    )

    assert result.loc[0, "is_substitutable"] == ""
    assert result.loc[0, "model_status"] == "LABELED"
    assert set(summary["method"]) == {"RULE_ONLY", "MODEL_ONLY", "RULE_AND_MODEL"}


def test_comparison_does_not_run_model_without_product_facet_profile():
    loader = TaxonomyLoader(
        {
            "categories": [
                {
                    "category_id": "c1",
                    "facets": [
                        {
                            "name": "form",
                            "order": 1,
                            "values": [
                                {"code": 0, "value": "ALL"},
                                {"code": 1, "value": "분말"},
                            ],
                        }
                    ],
                }
            ]
        }
    )
    demands = pd.DataFrame(
        [
            {
                "demand_id": "d1",
                "catalog_id": "catalog-1",
                "category_id": "c1",
                "extra_requirement": "",
            }
        ]
    )
    labeler = _FakeLabeler()
    before = labeler.call_count

    result, _ = compare_labeling_methods(demands, loader, {}, labeler, batch_size=1)

    assert result.loc[0, "rule_status"] == "REVIEW"
    assert result.loc[0, "rule_label"] == ""
    assert result.loc[0, "model_status"] == "MODEL_FAILURE"
    assert "PRODUCT_FACET_PROFILE_MISSING" in result.loc[0, "model_warnings"]
    assert labeler.call_count == before
