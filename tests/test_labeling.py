import pandas as pd
import pytest

from moongcheap_ai.data_foundation.demand_label_comparison import (
    _apply_model_result,
    _normalise_model_facet_values,
)
from moongcheap_ai.data_foundation.facet_codebook import (
    build_clustering_input,
    load_codebook,
)
from moongcheap_ai.data_foundation.labeling import (
    TaxonomyLoader,
    TaxonomyValidationError,
    build_product_facet_map,
    label_demands,
    taxonomy_from_category_facet_rows,
)

TAXONOMY = {
    "categories": [
        {
            "category_id": "C1",
            "facets": [
                {
                    "name": "sugar_type",
                    "order": 1,
                    "values": [
                        {"code": 0, "value": "ALL", "aliases": []},
                        {"code": 2, "value": "sugar_free", "aliases": ["무설탕"]},
                    ],
                }
            ],
        }
    ]
}
FORM_PROFILE = [
    {
        "category_id": "C1",
        "facet_name": "form",
        "mapping_status": "MAPPED",
        "value": "정제",
    }
]


def test_loader_matches_alias_and_defaults_all() -> None:
    loader = TaxonomyLoader(TAXONOMY)
    matched, warnings = loader.resolve("C1", "무설탕으로")
    assert matched["sugar_type"]["code"] == 2
    assert not warnings
    all_values, _ = loader.resolve("C1", "")
    assert all_values["sugar_type"]["code"] == 0


def test_batch_keeps_required_output_columns() -> None:
    loader = TaxonomyLoader(TAXONOMY)
    profile = {
        "P1": [
            {
                "category_id": "C1",
                "facet_name": "sugar_type",
                "mapping_status": "MAPPED",
                "value": "sugar_free",
            }
        ]
    }
    result = label_demands(
        pd.DataFrame(
            [
                {
                    "demand_id": "D1",
                    "catalog_id": "P1",
                    "category_id": "C1",
                    "extra_requirement": "무설탕으로",
                    "desired_quantity": "2",
                }
            ]
        ),
        loader,
        product_facet_map=profile,
    )
    assert result.iloc[0]["label"] == "2"
    assert result.iloc[0]["label_status"] == "LABELED"
    assert result.iloc[0]["quantity"] == "2"


@pytest.mark.parametrize(
    "requirement",
    [
        "무설탕 말아 주세요",
        "무설탕을 원하지 않아요",
        "무설탕보다는 설탕",
        "무설탕이 별로예요",
        "무설탕이나 저당 중 하나",
    ],
)
def test_direct_rule_labeling_does_not_turn_non_positive_text_into_override(
    requirement: str,
) -> None:
    loader = TaxonomyLoader(
        {
            "categories": [
                {
                    "category_id": "C1",
                    "facets": [
                        {
                            "name": "sweetener",
                            "order": 1,
                            "values": [
                                {"code": 0, "value": "ALL"},
                                {"code": 1, "value": "sugar", "aliases": ["설탕"]},
                                {
                                    "code": 2,
                                    "value": "sugar_free",
                                    "aliases": ["무설탕"],
                                },
                            ],
                        }
                    ],
                }
            ]
        }
    )
    product_facets = {
        "P1": [
            {
                "category_id": "C1",
                "facet_name": "sweetener",
                "mapping_status": "MAPPED",
                "value": "설탕",
                "value_code": "1",
            }
        ]
    }

    result = label_demands(
        pd.DataFrame(
            [
                {
                    "demand_id": "D1",
                    "catalog_id": "P1",
                    "category_id": "C1",
                    "extra_requirement": requirement,
                }
            ]
        ),
        loader,
        product_facet_map=product_facets,
    )

    assert result.iloc[0]["label"] == "1"
    assert result.iloc[0]["interpretation_status"] == "UNRESOLVED"
    assert (
        "non-positive requirement retained product Facet baseline"
        in result.iloc[0]["label_warnings"]
    )


def test_direct_rule_labeling_still_applies_clear_positive_override() -> None:
    loader = TaxonomyLoader(
        {
            "categories": [
                {
                    "category_id": "C1",
                    "facets": [
                        {
                            "name": "sweetener",
                            "order": 1,
                            "values": [
                                {"code": 0, "value": "ALL"},
                                {"code": 1, "value": "sugar", "aliases": ["설탕"]},
                                {
                                    "code": 2,
                                    "value": "sugar_free",
                                    "aliases": ["무설탕"],
                                },
                            ],
                        }
                    ],
                }
            ]
        }
    )
    result = label_demands(
        pd.DataFrame(
            [
                {
                    "demand_id": "D1",
                    "catalog_id": "P1",
                    "category_id": "C1",
                    "extra_requirement": "무설탕을 원해요",
                }
            ]
        ),
        loader,
        product_facet_map={
            "P1": [
                {
                    "category_id": "C1",
                    "facet_name": "sweetener",
                    "mapping_status": "MAPPED",
                    "value": "설탕",
                    "value_code": "1",
                }
            ]
        },
    )

    assert result.iloc[0]["label"] == "2"
    assert result.iloc[0]["interpretation_status"] == "PARSED"


def test_duplicate_value_codes_are_rejected() -> None:
    invalid = {
        "categories": [
            {
                "category_id": "C1",
                "facets": [{"name": "f", "values": [{"code": 0}, {"code": 0}]}],
            }
        ]
    }
    with pytest.raises(TaxonomyValidationError):
        TaxonomyLoader(invalid)


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ([{"code": -1, "value": "분말"}, {"code": 0, "value": "ALL"}], "non-negative"),
        ([{"code": 0.5, "value": "ALL"}], "invalid value code"),
        ([{"code": False, "value": "ALL"}], "invalid value code"),
        ([{"code": 0, "value": "UNKNOWN"}], "code 0 must be ALL"),
        (
            [{"code": 0, "value": "ALL"}, {"code": 1, "value": "ALL"}],
            "ALL must use code 0",
        ),
    ],
)
def test_taxonomy_rejects_invalid_all_and_negative_codes(
    values: list[dict[str, object]], message: str
) -> None:
    invalid = {
        "categories": [
            {
                "category_id": "C1",
                "facets": [{"name": "f", "values": values}],
            }
        ]
    }

    with pytest.raises(TaxonomyValidationError, match=message):
        TaxonomyLoader(invalid)


def test_malformed_taxonomy_types_raise_domain_validation_error() -> None:
    for invalid in [
        None,
        [],
        {"categories": [None]},
        {"categories": [{"category_id": "C1", "facets": [None]}]},
    ]:
        with pytest.raises(TaxonomyValidationError):
            TaxonomyLoader(invalid)


def test_taxonomy_rejects_null_contract_names_instead_of_stringifying_them() -> None:
    malformed = [
        {"categories": [{"category_id": None, "facets": []}]},
        {
            "categories": [
                {
                    "category_id": "C1",
                    "facets": [
                        {
                            "name": None,
                            "order": 1,
                            "values": [
                                {"code": 0, "value": "ALL"},
                                {"code": 1, "value": "value"},
                            ],
                        }
                    ],
                }
            ]
        },
        {
            "categories": [
                {
                    "category_id": "C1",
                    "facets": [
                        {
                            "name": "form",
                            "order": 1,
                            "values": [
                                {"code": 0, "value": "ALL"},
                                {"code": 1, "value": None},
                            ],
                        }
                    ],
                }
            ]
        },
        {
            "categories": [
                {
                    "category_id": "C1",
                    "facets": [
                        {
                            "name": "form",
                            "order": 1,
                            "values": [{"code": 0}],
                        }
                    ],
                }
            ]
        },
    ]

    for taxonomy in malformed:
        with pytest.raises(TaxonomyValidationError):
            TaxonomyLoader(taxonomy)


def test_taxonomy_rejects_missing_category_id_and_malformed_aliases() -> None:
    for taxonomy in [
        {"categories": [{"facets": []}]},
        {
            "categories": [
                {
                    "category_id": "C1",
                    "facets": [
                        {
                            "name": "form",
                            "values": [
                                {"code": 0, "value": "ALL"},
                                {"code": 1, "value": "분말", "aliases": "파우더"},
                            ],
                        }
                    ],
                }
            ]
        },
        {
            "categories": [
                {
                    "category_id": "C1",
                    "facets": [
                        {
                            "name": "form",
                            "values": [
                                {"code": 0, "value": "ALL"},
                                {"code": 1, "value": "분말", "aliases": [None]},
                            ],
                        }
                    ],
                }
            ]
        },
        {
            "categories": [
                {
                    "category_id": "C1",
                    "facets": [
                        {
                            "name": "form",
                            "values": [{"code": 0, "value": "ALL"}, {"code": 1}],
                        }
                    ],
                }
            ]
        },
    ]:
        with pytest.raises(TaxonomyValidationError):
            TaxonomyLoader(taxonomy)


def test_taxonomy_json_duplicate_keys_are_rejected(tmp_path) -> None:
    path = tmp_path / "duplicate-taxonomy.json"
    path.write_text(
        '{"categories": [], "categories": [{"category_id": "C1", "facets": []}]}',
        encoding="utf-8",
    )

    with pytest.raises(TaxonomyValidationError, match="duplicate JSON key"):
        TaxonomyLoader.from_path(path)


def test_category_facet_rejects_duplicate_json_keys_and_handles_missing_scalar() -> (
    None
):
    with pytest.raises(TaxonomyValidationError, match="duplicate JSON key"):
        taxonomy_from_category_facet_rows(
            pd.DataFrame(
                [
                    {
                        "category_id": "C1",
                        "category_facet": '{"category_id":"C1","category_id":"C2","facets":[]}',
                    }
                ]
            )
        )

    with pytest.raises(TaxonomyValidationError, match="no usable"):
        taxonomy_from_category_facet_rows(
            pd.DataFrame([{"category_id": pd.NA, "category_facet": pd.NA}])
        )


@pytest.mark.parametrize(
    "facet_json",
    [
        '{"category_id":null,"facets":[]}',
        '{"category_id":true,"facets":[]}',
        '{"category_id":"","facets":[]}',
    ],
)
def test_category_facet_does_not_replace_explicit_invalid_category_key(
    facet_json: str,
) -> None:
    with pytest.raises(TaxonomyValidationError, match="category.facet category_id"):
        taxonomy_from_category_facet_rows(
            pd.DataFrame([{"category_id": "42", "category_facet": facet_json}])
        )


def test_non_contiguous_facet_orders_are_rejected() -> None:
    invalid = {
        "categories": [
            {
                "category_id": "C1",
                "facets": [
                    {"name": "a", "order": 1, "values": [{"code": 0}]},
                    {"name": "b", "order": 3, "values": [{"code": 0}]},
                ],
            }
        ]
    }
    with pytest.raises(TaxonomyValidationError):
        TaxonomyLoader(invalid)


def test_product_baseline_label_uses_declared_facet_order_not_json_order() -> None:
    loader = TaxonomyLoader(
        {
            "categories": [
                {
                    "category_id": "C1",
                    "facets": [
                        {
                            "name": "second",
                            "order": 2,
                            "values": [
                                {"code": 0, "value": "ALL"},
                                {"code": 2, "value": "B"},
                            ],
                        },
                        {
                            "name": "first",
                            "order": 1,
                            "values": [
                                {"code": 0, "value": "ALL"},
                                {"code": 1, "value": "A"},
                            ],
                        },
                    ],
                }
            ]
        }
    )

    defaults, warnings = loader.product_defaults(
        "C1",
        [
            {
                "category_id": "C1",
                "facet_name": "second",
                "mapping_status": "MAPPED",
                "value": "B",
            },
            {
                "category_id": "C1",
                "facet_name": "first",
                "mapping_status": "MAPPED",
                "value": "A",
            },
        ],
    )

    assert not warnings
    assert list(defaults) == ["first", "second"]
    assert loader.encode(defaults) == "1-2"


def test_root_taxonomy_uses_declared_facet_order() -> None:
    loader = TaxonomyLoader(
        {
            "facets": [
                {
                    "name": "second",
                    "order": 2,
                    "values": [{"code": 0, "value": "ALL"}],
                },
                {
                    "name": "first",
                    "order": 1,
                    "values": [{"code": 0, "value": "ALL"}],
                },
            ]
        }
    )

    assert [facet["name"] for facet in loader.root_category["facets"]] == [
        "first",
        "second",
    ]


def test_unmatched_requirement_is_recorded_as_unresolved() -> None:
    loader = TaxonomyLoader(TAXONOMY)
    profile = {
        "P3": [
            {
                "category_id": "C1",
                "facet_name": "sugar_type",
                "mapping_status": "MAPPED",
                "value": "sugar_free",
            }
        ]
    }
    result = label_demands(
        pd.DataFrame(
            [
                {
                    "demand_id": "D3",
                    "catalog_id": "P3",
                    "category_id": "C1",
                    "extra_requirement": "카페인 함량이 낮은 제품",
                }
            ]
        ),
        loader,
        product_facet_map=profile,
    )
    assert result.iloc[0]["label_status"] == "LABELED"
    assert result.iloc[0]["label"] == "2"
    assert "카페인 함량이 낮은 제품" in result.iloc[0]["unresolved_items"]


def test_missing_product_profile_is_not_fabricated_as_all() -> None:
    result = label_demands(
        pd.DataFrame(
            [
                {
                    "demand_id": "D",
                    "catalog_id": "P",
                    "category_id": "C1",
                    "extra_requirement": "",
                }
            ]
        ),
        TaxonomyLoader(TAXONOMY),
    )

    assert result.iloc[0]["label_status"] == "REVIEW"
    assert result.iloc[0]["label"] == ""


def test_negative_requirement_keeps_the_original_product_facet():
    loader = TaxonomyLoader(
        {
            "categories": [
                {
                    "category_id": "C1",
                    "facets": [
                        {
                            "name": "form",
                            "order": 1,
                            "values": [
                                {"code": 0, "value": "ALL"},
                                {"code": 1, "value": "분말"},
                                {"code": 2, "value": "캡슐"},
                            ],
                        }
                    ],
                }
            ]
        }
    )
    profile = {
        "P": [
            {
                "category_id": "C1",
                "facet_name": "form",
                "mapping_status": "MAPPED",
                "value": "캡슐",
            }
        ]
    }

    result = label_demands(
        pd.DataFrame(
            [
                {
                    "demand_id": "D",
                    "catalog_id": "P",
                    "category_id": "C1",
                    "extra_requirement": "분말이 아니라 캡슐을 원해요",
                }
            ]
        ),
        loader,
        product_facet_map=profile,
    )

    assert result.loc[0, "label"] == "2"
    assert result.loc[0, "label_status"] == "LABELED"
    assert '"form":{"code":2' in result.loc[0, "facet_values"]


def test_no_requirement_phrase_defaults_to_all_without_review() -> None:
    loader = TaxonomyLoader(TAXONOMY)
    profile = {
        "P4": [
            {
                "category_id": "C1",
                "facet_name": "sugar_type",
                "mapping_status": "MAPPED",
                "value": "sugar_free",
            }
        ]
    }
    result = label_demands(
        pd.DataFrame(
            [
                {
                    "demand_id": "D4",
                    "catalog_id": "P4",
                    "category_id": "C1",
                    "extra_requirement": "조건 없음",
                }
            ]
        ),
        loader,
        product_facet_map=profile,
    )
    assert result.iloc[0]["label"] == "2"
    assert result.iloc[0]["label_status"] == "LABELED"


def test_batch_can_resolve_category_through_catalog_id() -> None:
    loader = TaxonomyLoader(TAXONOMY)
    profile = {
        "P2": [
            {
                "category_id": "C1",
                "facet_name": "sugar_type",
                "mapping_status": "MAPPED",
                "value": "sugar_free",
            }
        ]
    }
    result = label_demands(
        pd.DataFrame(
            [{"demand_id": "D2", "catalog_id": "P2", "extra_requirement": "무설탕"}]
        ),
        loader,
        {"P2": "C1"},
        profile,
    )
    assert result.iloc[0]["label"] == "2"


def test_batch_treats_nan_identifiers_and_requirements_as_blank() -> None:
    loader = TaxonomyLoader(
        {
            "categories": [
                {
                    "category_id": "C1",
                    "facets": [
                        {
                            "name": "form",
                            "order": 1,
                            "values": [{"code": 0, "value": "ALL"}],
                        }
                    ],
                }
            ]
        }
    )
    result = label_demands(
        pd.DataFrame(
            [
                {
                    "demand_id": "D1",
                    "catalog_id": float("nan"),
                    "category_id": float("nan"),
                    "extra_requirement": float("nan"),
                }
            ]
        ),
        loader,
    )
    assert result.iloc[0]["category_id"] == ""
    assert result.iloc[0]["label_status"] == "REVIEW"
    assert result.iloc[0]["unresolved_items"] == "[]"


def test_product_facets_are_defaults_and_extra_requirement_wins() -> None:
    loader = TaxonomyLoader(
        {
            "categories": [
                {
                    "category_id": "C1",
                    "facets": [
                        {
                            "name": "form",
                            "order": 1,
                            "values": [
                                {"code": 0, "value": "ALL"},
                                {"code": 1, "value": "정제"},
                                {"code": 2, "value": "분말"},
                            ],
                        },
                        {
                            "name": "sugar",
                            "order": 2,
                            "values": [
                                {"code": 0, "value": "ALL"},
                                {"code": 1, "value": "무설탕"},
                                {"code": 2, "value": "당류"},
                            ],
                        },
                    ],
                }
            ]
        }
    )
    facets = build_product_facet_map(
        pd.DataFrame(
            [
                {
                    "source_product_id": "P1",
                    "category_id": "C1",
                    "facet_name": "form",
                    "value": "정제",
                    "mapping_status": "MAPPED",
                },
                {
                    "source_product_id": "P1",
                    "category_id": "C1",
                    "facet_name": "sugar",
                    "value": "무설탕",
                    "mapping_status": "MAPPED",
                },
            ]
        )
    )
    result = label_demands(
        pd.DataFrame(
            [
                {
                    "demand_id": "D1",
                    "catalog_id": "catalog-seed-P1",
                    "category_id": "C1",
                    "extra_requirement": "분말",
                    "is_substitutable": False,
                }
            ]
        ),
        loader,
        product_facet_map=facets,
    )
    assert '"form":{"code":2' in result.loc[0, "facet_values"]
    assert '"sugar":{"code":1' in result.loc[0, "facet_values"]


def test_product_facets_can_be_indexed_by_backend_catalog_id() -> None:
    mapping = build_product_facet_map(
        pd.DataFrame(
            [
                {
                    "source_product_id": "source-1",
                    "catalog_id": "987",
                    "category_id": "C1",
                    "facet_name": "form",
                    "value": "정제",
                    "mapping_status": "MAPPED",
                }
            ]
        )
    )
    assert "987" in mapping
    assert "source-1" in mapping


def test_codebook_and_clustering_vector_keep_facet_identity(tmp_path) -> None:
    taxonomy_path = tmp_path / "taxonomy.json"
    taxonomy_path.write_text(
        __import__("json").dumps(
            {
                "categories": [
                    {
                        "category_id": "C1",
                        "facets": [
                            {
                                "name": "form",
                                "order": 1,
                                "values": [
                                    {"code": 0, "value": "ALL"},
                                    {"code": 1, "value": "정제"},
                                ],
                            },
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    codebook = load_codebook(taxonomy_path)
    result = build_clustering_input(
        pd.DataFrame(
            [
                {
                    "demand_id": "D1",
                    "catalog_id": "P1",
                    "category_id": "C1",
                    "label": "1",
                    "facet_values": '{"form":{"code":1,"value":"정제"}}',
                    "is_substitutable": "false",
                    "desired_price_min": "0",
                    "desired_price_max": "10000",
                    "quantity": "1",
                }
            ]
        ),
        codebook,
    )
    assert result.loc[0, "facet_label"] == "1"
    assert result.loc[0, "facet_1_form_code"] == 1
    assert result.loc[0, "taxonomy_version"] == "v2.1"


def test_llm_result_is_limited_to_taxonomy_codes() -> None:
    loader = TaxonomyLoader(
        {
            "categories": [
                {
                    "category_id": "C1",
                    "facets": [
                        {
                            "name": "form",
                            "order": 1,
                            "values": [
                                {"code": 0, "value": "ALL"},
                                {"code": 1, "value": "정제"},
                            ],
                        },
                    ],
                }
            ]
        }
    )
    row = pd.Series({"category_id": "C1"})
    values, warnings = _apply_model_result(row, {"form": 99}, loader, FORM_PROFILE)
    assert values["form"]["code"] == 1
    assert warnings


def test_llm_result_cannot_reintroduce_deprecated_taxonomy_value() -> None:
    loader = TaxonomyLoader(
        {
            "categories": [
                {
                    "category_id": "C1",
                    "facets": [
                        {
                            "name": "form",
                            "order": 1,
                            "values": [
                                {"code": 0, "value": "ALL"},
                                {"code": 1, "value": "정제"},
                                {
                                    "code": 2,
                                    "value": "옛정제",
                                    "status": "DEPRECATED",
                                    "canonical_code": 1,
                                },
                            ],
                        },
                    ],
                }
            ]
        }
    )
    row = pd.Series({"category_id": "C1"})

    values, warnings = _apply_model_result(row, {"form": 2}, loader, FORM_PROFILE)

    assert values["form"]["code"] == 1
    assert warnings


def test_product_baseline_rejects_deprecated_taxonomy_value() -> None:
    loader = TaxonomyLoader(
        {
            "categories": [
                {
                    "category_id": "C1",
                    "facets": [
                        {
                            "name": "form",
                            "order": 1,
                            "values": [
                                {"code": 0, "value": "ALL"},
                                {"code": 1, "value": "정제"},
                                {
                                    "code": 2,
                                    "value": "옛정제",
                                    "status": "DEPRECATED",
                                    "canonical_code": 1,
                                },
                            ],
                        }
                    ],
                }
            ]
        }
    )

    values, warnings = loader.product_defaults(
        "C1",
        [
            {
                "category_id": "C1",
                "facet_name": "form",
                "mapping_status": "MAPPED",
                "value": "옛정제",
                "value_code": "2",
            }
        ],
    )

    assert values["form"]["code"] == 0
    assert warnings == ["deprecated product Facet value is not valid: form=옛정제"]


def test_llm_numeric_facet_key_is_not_guessed_by_position() -> None:
    loader = TaxonomyLoader(
        {
            "categories": [
                {
                    "category_id": "C1",
                    "facets": [
                        {
                            "name": "form",
                            "order": 1,
                            "facet_id": 1,
                            "values": [
                                {"code": 0, "value": "ALL"},
                                {"code": 1, "value": "정제"},
                                {"code": 2, "value": "분말"},
                            ],
                        },
                        {
                            "name": "taste",
                            "order": 2,
                            "facet_id": 2,
                            "values": [
                                {"code": 0, "value": "ALL"},
                                {"code": 1, "value": "레몬"},
                                {"code": 2, "value": "딸기"},
                            ],
                        },
                    ],
                }
            ]
        }
    )
    row = pd.Series({"category_id": "C1"})
    baseline = {
        "form": {"code": 1, "value": "정제", "matched_alias": "product"},
        "taste": {"code": 1, "value": "레몬", "matched_alias": "product"},
    }

    values, warnings = _apply_model_result(
        row,
        {"facet_1": 2},
        loader,
        baseline_values=baseline,
    )

    assert values["taste"]["value"] == "레몬"
    assert values["taste"]["matched_alias"] == "product"
    assert warnings == ["LLM facet key is not an exact taxonomy name: facet_1"]


def test_model_single_facet_object_is_converted_to_mapping() -> None:
    result = _normalise_model_facet_values({"facet_name": "form", "value": "정제"})
    assert result == {"form": {"value": "정제"}}


def test_llm_category_prefixed_facet_is_not_accepted_as_exact_name() -> None:
    loader = TaxonomyLoader(
        {
            "categories": [
                {
                    "category_id": "C1",
                    "facets": [
                        {
                            "name": "form",
                            "order": 1,
                            "values": [
                                {"code": 0, "value": "ALL"},
                                {"code": 1, "value": "정제"},
                            ],
                        },
                    ],
                }
            ]
        }
    )
    row = pd.Series({"category_id": "C1"})
    values, warnings = _apply_model_result(
        row, {"health:C2:form": 1, "form": None}, loader, FORM_PROFILE
    )
    assert values["form"]["code"] == 1
    assert warnings == [
        "LLM facet key is not an exact taxonomy name: health:C2:form",
        "LLM returned null facet value: form",
    ]


def test_llm_category_prefixed_facet_does_not_override_exact_facet_value() -> None:
    loader = TaxonomyLoader(
        {
            "categories": [
                {
                    "category_id": "C1",
                    "facets": [
                        {
                            "name": "form",
                            "order": 1,
                            "values": [
                                {"code": 0, "value": "ALL"},
                                {"code": 1, "value": "정제"},
                                {"code": 2, "value": "분말"},
                            ],
                        },
                    ],
                }
            ]
        }
    )
    row = pd.Series(
        {
            "category_id": "C1",
            "extra_requirement": "정제",
        }
    )

    values, warnings = _apply_model_result(
        row,
        {"health:C2:form": 2, "form": 1},
        loader,
        baseline_values={
            "form": {"code": 2, "value": "분말", "matched_alias": "product"}
        },
    )

    assert values["form"]["code"] == 1
    assert warnings == ["LLM facet key is not an exact taxonomy name: health:C2:form"]


def test_hybrid_model_override_keeps_unmentioned_product_defaults() -> None:
    loader = TaxonomyLoader(
        {
            "categories": [
                {
                    "category_id": "C1",
                    "facets": [
                        {
                            "name": "form",
                            "order": 1,
                            "values": [
                                {"code": 0, "value": "ALL"},
                                {"code": 1, "value": "정제"},
                                {"code": 2, "value": "분말"},
                            ],
                        },
                        {
                            "name": "sugar",
                            "order": 2,
                            "values": [
                                {"code": 0, "value": "ALL"},
                                {"code": 1, "value": "무설탕"},
                            ],
                        },
                    ],
                }
            ]
        }
    )
    row = pd.Series({"category_id": "C1"})
    values, warnings = _apply_model_result(
        row,
        {"sugar": 1},
        loader,
        [
            {
                "category_id": "C1",
                "facet_name": "form",
                "value": "정제",
                "mapping_status": "MAPPED",
            },
            {
                "category_id": "C1",
                "facet_name": "sugar",
                "value": "무설탕",
                "mapping_status": "MAPPED",
            },
        ],
    )
    assert values["form"]["code"] == 1
    assert values["sugar"]["code"] == 1
    assert not warnings


def test_pandas_missing_requirement_is_treated_as_empty() -> None:
    loader = TaxonomyLoader(TAXONOMY)
    values, warnings = loader.resolve("C1", pd.NA)
    assert all(value["code"] == 0 for value in values.values())
    assert warnings == []
