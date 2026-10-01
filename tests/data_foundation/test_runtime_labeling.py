import json

import pandas as pd
import pytest

from moongcheap_ai.data_foundation import runtime_job
from moongcheap_ai.data_foundation.backend_contract import (
    build_label_result_payload,
    validate_backend_response,
)
from moongcheap_ai.data_foundation.demand_label_comparison import (
    LLMLabelingError,
    OllamaDemandLabeler,
    _apply_model_result,
    ensure_ollama_model_available,
)
from moongcheap_ai.data_foundation.labeling import (
    TaxonomyLoader,
    taxonomy_from_category_facet_rows,
)
from moongcheap_ai.data_foundation.runtime_job import (
    _first_env,
    _labeling_status_counts,
    _limit_llm_target,
    _llm_pages,
)
from moongcheap_ai.data_foundation.runtime_job import run_batch as _run_batch


def _explicit_mapped_product_facets(demands, taxonomy):
    """Give unit tests complete synthetic profiles using valid taxonomy values."""
    payload = (
        taxonomy
        if isinstance(taxonomy, dict)
        else TaxonomyLoader.from_path(taxonomy).taxonomy
    )
    categories = {
        str(category["category_id"]): category
        for category in payload.get("categories", [])
    }
    result = {}
    for _, demand in demands.fillna("").iterrows():
        catalog_id = str(demand.get("catalog_id", "")).strip()
        category_id = str(demand.get("category_id", "")).strip()
        category = categories.get(category_id)
        if not catalog_id or category is None:
            continue
        result[catalog_id] = [
            {
                "catalog_id": catalog_id,
                "category_id": category_id,
                "facet_name": str(facet["name"]),
                "mapping_status": "MAPPED",
                "value": str(
                    next(
                        value["value"]
                        for value in facet.get("values", [])
                        if int(value.get("code", 0)) > 0
                    )
                ),
            }
            for facet in category.get("facets", [])
        ]
    return result


def run_batch(demands, taxonomy_path, **kwargs):
    """Use explicit mapped test profiles unless a test supplies its own."""
    product_facet_map = kwargs.pop("product_facet_map", None)
    if product_facet_map is None:
        product_facet_map = _explicit_mapped_product_facets(
            demands, kwargs.get("taxonomy_payload") or taxonomy_path
        )
    return _run_batch(
        demands,
        taxonomy_path,
        product_facet_map=product_facet_map,
        **kwargs,
    )


def test_batch_status_log_counts_review_without_logging_requirement_text() -> None:
    frame = pd.DataFrame({"label_status": ["LABELED", "REVIEW", "REVIEW", None]})

    assert _labeling_status_counts(frame) == {"": 1, "LABELED": 1, "REVIEW": 2}
    assert _labeling_status_counts(pd.DataFrame()) == {}


def test_llm_target_is_never_dropped_and_positive_limit_creates_pages() -> None:
    target = pd.DataFrame({"demand_id": [str(index) for index in range(105)]})

    assert len(_limit_llm_target(target, 0)) == 105
    assert len(_limit_llm_target(target, -1)) == 105
    assert len(_limit_llm_target(target, 100)) == 105
    assert [len(page) for page in _llm_pages(target, 100)] == [100, 5]


def test_runtime_accepts_cloud_develop_model2_environment_aliases() -> None:
    source = {
        "A_MODEL2_FALLBACK_ENABLED": "true",
        "A_MODEL2_FALLBACK_MODEL": "qwen2.5:3b",
        "A_MODEL2_OLLAMA_BASE_URL": "http://127.0.0.1:11434",
    }

    assert _first_env(source, "A_LLM_ENABLED", "A_MODEL2_FALLBACK_ENABLED") == "true"
    assert _first_env(source, "A_LLM_MODEL", "A_MODEL2_FALLBACK_MODEL") == "qwen2.5:3b"
    assert (
        _first_env(source, "A_LLM_ENDPOINT", "A_MODEL2_OLLAMA_BASE_URL")
        == "http://127.0.0.1:11434"
    )


def test_ollama_model_preflight_accepts_exact_model(monkeypatch) -> None:
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"models": [{"name": "qwen2.5:7b-instruct"}]}).encode()

    monkeypatch.setattr(
        "moongcheap_ai.data_foundation.demand_label_comparison.urllib.request.urlopen",
        lambda request, timeout: Response(),
    )
    ensure_ollama_model_available("http://ollama:11434", "qwen2.5:7b-instruct")


def test_ollama_model_preflight_rejects_missing_model(monkeypatch) -> None:
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"models": [{"name": "other:latest"}]}).encode()

    monkeypatch.setattr(
        "moongcheap_ai.data_foundation.demand_label_comparison.urllib.request.urlopen",
        lambda request, timeout: Response(),
    )
    with pytest.raises(LLMLabelingError, match="not available"):
        ensure_ollama_model_available("http://ollama:11434", "qwen2.5:7b-instruct")


def test_main_fails_before_processing_when_required_model_preflight_fails(
    monkeypatch, tmp_path, capsys
) -> None:
    monkeypatch.setenv("A_LLM_ENABLED", "true")
    monkeypatch.setenv("A_LLM_MODEL", "qwen2.5:7b-instruct")
    monkeypatch.setenv("A_DATABASE_URL", "postgresql://unused")

    def fail_preflight(*args, **kwargs):
        raise LLMLabelingError("Ollama model is not available")

    monkeypatch.setattr(runtime_job, "ensure_ollama_model_available", fail_preflight)
    monkeypatch.setattr(
        runtime_job,
        "open_postgres",
        lambda *_args, **_kwargs: pytest.fail("DB must not be opened after failed preflight"),
    )
    output_path = tmp_path / "result.csv"

    code = runtime_job.main(
        [
            "--write-db",
            "--output",
            str(output_path),
        ]
    )

    captured = capsys.readouterr()
    assert code == 1, f"stdout={captured.out}; stderr={captured.err}"
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "status": "FAILED",
        "error": "required Ollama model preflight failed: Ollama model is not available",
    }
    assert not output_path.exists()


@pytest.mark.parametrize(
    ("rows", "results", "message"),
    [
        (
            [{"demand_id": "1", "category_id": "c1"}],
            [
                {"demand_id": "1", "facet_values": {}},
                {"demand_id": "1", "facet_values": {}},
            ],
            "duplicate demand ID",
        ),
        (
            [{"demand_id": "1", "category_id": "c1"}],
            [{"demand_id": "extra", "facet_values": {}}],
            "unexpected demand ID",
        ),
        (
            [
                {"demand_id": "1", "category_id": "c1"},
                {"demand_id": "2", "category_id": "c1"},
            ],
            [{"demand_id": "1", "facet_values": {}}],
            "omitted demand IDs",
        ),
    ],
)
def test_ollama_rejects_duplicate_unexpected_or_missing_result_ids(
    monkeypatch, rows, results, message
) -> None:
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"response": json.dumps({"results": results})}).encode()

    monkeypatch.setattr(
        "moongcheap_ai.data_foundation.demand_label_comparison.urllib.request.urlopen",
        lambda request, timeout: Response(),
    )
    labeler = OllamaDemandLabeler("test")
    with pytest.raises(LLMLabelingError, match=message):
        labeler.classify(rows, TaxonomyLoader({"categories": []}))
    assert labeler.call_count == 1


def test_ollama_rejects_duplicate_or_missing_request_ids_before_http(
    monkeypatch,
) -> None:
    def unexpected_http_call(*args, **kwargs):
        raise AssertionError("invalid requests must not be sent")

    monkeypatch.setattr(
        "moongcheap_ai.data_foundation.demand_label_comparison.urllib.request.urlopen",
        unexpected_http_call,
    )
    labeler = OllamaDemandLabeler("test")
    loader = TaxonomyLoader({"categories": []})
    for rows, expected in [
        (
            [
                {"demand_id": "1", "category_id": "c1"},
                {"demand_id": "1", "category_id": "c1"},
            ],
            "duplicate demand IDs",
        ),
        ([{"demand_id": " "}], "missing demand_id"),
        ([{}], "missing demand_id"),
        ([{"demand_id": "1"}], "missing category_id"),
    ]:
        with pytest.raises(LLMLabelingError, match=expected):
            labeler.classify(rows, loader)
    assert labeler.call_count == 0


@pytest.mark.parametrize(
    "envelope", [[], None, 3, {"response": "3"}, {"response": "{}"}]
)
def test_ollama_rejects_malformed_response_shapes(monkeypatch, envelope) -> None:
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(envelope).encode()

    monkeypatch.setattr(
        "moongcheap_ai.data_foundation.demand_label_comparison.urllib.request.urlopen",
        lambda request, timeout: Response(),
    )
    labeler = OllamaDemandLabeler("test")
    with pytest.raises(LLMLabelingError):
        labeler.classify(
            [{"demand_id": "1", "category_id": "c1"}],
            TaxonomyLoader({"categories": []}),
        )
    assert labeler.call_count == 1


def test_ollama_rejects_duplicate_json_keys(monkeypatch) -> None:
    raw = (
        b'{"response":"{\\"results\\":[{\\"demand_id\\":\\"1\\",'
        b'\\"facet_values\\":{\\"form\\":1,\\"form\\":2}}]}"}'
    )

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return raw

    monkeypatch.setattr(
        "moongcheap_ai.data_foundation.demand_label_comparison.urllib.request.urlopen",
        lambda request, timeout: Response(),
    )
    with pytest.raises(LLMLabelingError, match="duplicate JSON key"):
        OllamaDemandLabeler("test").classify(
            [{"demand_id": "1", "category_id": "c1"}],
            TaxonomyLoader({"categories": []}),
        )


def test_ollama_empty_request_is_noop(monkeypatch) -> None:
    def unexpected_http_call(*args, **kwargs):
        raise AssertionError("empty batches must not call Ollama")

    monkeypatch.setattr(
        "moongcheap_ai.data_foundation.demand_label_comparison.urllib.request.urlopen",
        unexpected_http_call,
    )
    labeler = OllamaDemandLabeler("test")
    assert labeler.classify([], TaxonomyLoader({"categories": []})) == {}
    assert labeler.call_count == 0


def test_backend_payload_excludes_all_unresolved_review_statuses() -> None:
    frame = pd.DataFrame(
        [
            {
                "demand_id": "1",
                "catalog_id": "10",
                "category_id": "c1",
                "label": "1-2",
                "facet_values": '{"form":{"code":1},"taste":{"code":2}}',
                "label_status": "LABELED",
            },
            {
                "demand_id": "2",
                "catalog_id": "11",
                "category_id": "c1",
                "label": "0",
                "facet_values": "{}",
                "label_status": "LABELED_WITH_REVIEW",
            },
            {
                "demand_id": "3",
                "catalog_id": "12",
                "category_id": "c1",
                "label": "0",
                "facet_values": "{}",
                "label_status": "REVIEW",
            },
            {
                "demand_id": "4",
                "catalog_id": "13",
                "category_id": "c1",
                "label": "1",
                "facet_values": "{}",
                "label_status": "PARSED",
            },
        ]
    )

    payload = build_label_result_payload(frame, processed_at="2026-09-26T00:00:00Z")

    assert [row["demandId"] for row in payload["results"]] == [1]


def test_backend_payload_rejects_completed_label_without_product_facet_values() -> None:
    frame = pd.DataFrame(
        [
            {
                "demand_id": "1",
                "catalog_id": "10",
                "category_id": "c1",
                "label": "0",
                "facet_values": "{}",
                "label_status": "LABELED",
            }
        ]
    )

    with pytest.raises(ValueError, match="no product Facet values"):
        build_label_result_payload(frame, processed_at="2026-10-01T00:00:00Z")


def test_backend_payload_rejects_duplicate_normalized_demand_ids() -> None:
    frame = pd.DataFrame(
        [
            {
                "demand_id": "001",
                "catalog_id": "10",
                "category_id": "c1",
                "label": "1",
                "facet_values": '{"form":{"code":1}}',
                "label_status": "LABELED",
            },
            {
                "demand_id": "1",
                "catalog_id": "10",
                "category_id": "c1",
                "label": "1",
                "facet_values": '{"form":{"code":1}}',
                "label_status": "LABELED",
            },
        ]
    )

    with pytest.raises(ValueError, match="duplicate demand_id"):
        build_label_result_payload(frame, processed_at="2026-10-01T00:00:00Z")


@pytest.mark.parametrize(
    "facet_values",
    [
        '{"form":{"code":true}}',
        '{"form":{"code":1.5}}',
        '{"form":{"code":-1}}',
        '{"form":null}',
    ],
)
def test_backend_payload_rejects_non_integer_facet_codes(facet_values) -> None:
    frame = pd.DataFrame(
        [
            {
                "demand_id": "1",
                "catalog_id": "10",
                "category_id": "c1",
                "label": "1",
                "facet_values": facet_values,
                "label_status": "LABELED",
            }
        ]
    )

    with pytest.raises(ValueError, match="invalid Facet codes"):
        build_label_result_payload(frame, processed_at="2026-10-01T00:00:00Z")


@pytest.mark.parametrize("invalid_id", ["0", "-1", "1.0", "9223372036854775808", "abc"])
def test_backend_payload_rejects_non_backend_integer_ids(invalid_id) -> None:
    frame = pd.DataFrame(
        [
            {
                "demand_id": invalid_id,
                "catalog_id": "10",
                "category_id": "c1",
                "label": "1",
                "facet_values": '{"form":{"code":1}}',
                "label_status": "LABELED",
            }
        ]
    )

    with pytest.raises(ValueError, match="Backend ID|positive integers"):
        build_label_result_payload(frame, processed_at="2026-10-01T00:00:00Z")


@pytest.mark.parametrize("timestamp", ["", "not-a-timestamp", "2026-10-01T00:00:00"])
def test_backend_payload_requires_timezone_aware_timestamp(timestamp) -> None:
    with pytest.raises(ValueError, match="timezone-aware ISO-8601"):
        build_label_result_payload(pd.DataFrame(), processed_at=timestamp)


def test_backend_payload_rejects_duplicate_facet_json_keys() -> None:
    frame = pd.DataFrame(
        [
            {
                "demand_id": "1",
                "catalog_id": "10",
                "category_id": "c1",
                "label": "1",
                "facet_values": '{"form":{"code":1},"form":{"code":1}}',
                "label_status": "LABELED",
            }
        ]
    )

    with pytest.raises(ValueError, match="invalid facet_values JSON"):
        build_label_result_payload(frame, processed_at="2026-10-01T00:00:00Z")


def test_unresolved_rows_keep_catalog_defaults_without_llm_retry(
    tmp_path, monkeypatch
) -> None:
    taxonomy = {
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
    path = tmp_path / "taxonomy.json"
    path.write_text(json.dumps(taxonomy, ensure_ascii=False), encoding="utf-8")
    demands = pd.DataFrame(
        [
            {
                "demand_id": str(i),
                "catalog_id": str(i),
                "category_id": "c1",
                "extra_requirement": "조건 확인",
            }
            for i in range(3)
        ]
    )

    class UnexpectedLabeler:
        call_count = 0

        def __init__(self, *args, **kwargs):
            pass

        def classify(self, rows, loader):
            type(self).call_count += 1
            raise AssertionError("parser ambiguity should retain product defaults")

    monkeypatch.setattr(runtime_job, "OllamaDemandLabeler", UnexpectedLabeler)
    labeled, _ = runtime_job.run_batch(
        demands,
        path,
        product_facet_map=_explicit_mapped_product_facets(demands, path),
    )

    assert len(labeled) == 3
    assert set(labeled["label_status"]) == {"LABELED"}
    assert set(labeled["label_source"]) == {"PRODUCT_DEFAULT"}
    assert UnexpectedLabeler.call_count == 0


@pytest.mark.parametrize("outcome", ["review", "unavailable"])
def test_parser_review_uses_product_default_when_fallback_cannot_resolve(
    tmp_path, monkeypatch, outcome
) -> None:
    taxonomy = {
        "categories": [
            {
                "category_id": "c1",
                "facets": [
                    {
                        "facet_id": 1,
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

    class Labeler:
        calls = 0

        def __init__(self, *args, **kwargs):
            self.call_count = 0

        def classify(self, rows, loader):
            self.call_count += 1
            type(self).calls += 1
            if outcome == "unavailable":
                raise LLMLabelingError("temporary connection failure")
            return {"1": {"form": {"code": 1 if outcome == "accepted" else 0}}}

    monkeypatch.setattr(runtime_job, "OllamaDemandLabeler", Labeler)
    frame = pd.DataFrame(
        [
            {
                "demand_id": "1",
                "catalog_id": "1",
                "category_id": "c1",
                "extra_requirement": "조건 확인",
            }
        ]
    )
    labeled, _ = run_batch(
        frame,
        tmp_path / "unused.json",
        taxonomy_payload=taxonomy,
        model2_fallback_enabled=True,
    )
    assert Labeler.calls == 1
    assert labeled.loc[0, "label_status"] == "LABELED"
    assert labeled.loc[0, "label"] == "1"
    summary = labeled.attrs["model2_fallback"]
    assert summary["calls"] == 1
    assert summary["applied"] == 0
    assert summary["failed"] == int(outcome == "unavailable")
    assert summary["review"] == int(outcome == "review")


def test_model_value_with_matching_alias_has_positive_evidence() -> None:
    taxonomy = {
        "categories": [
            {
                "category_id": "c1",
                "facets": [
                    {
                        "facet_id": 1,
                        "name": "form",
                        "order": 1,
                        "values": [
                            {"code": 0, "value": "ALL"},
                            {"code": 1, "value": "분말", "aliases": ["가루"]},
                        ],
                    }
                ],
            }
        ]
    }

    row = pd.Series({"category_id": "c1", "extra_requirement": "가루 형태를 원해요"})
    values, warnings = _apply_model_result(
        row,
        {"form": {"code": 1}},
        TaxonomyLoader(taxonomy),
        [
            {
                "category_id": "c1",
                "facet_name": "form",
                "mapping_status": "MAPPED",
                "value": "분말",
            }
        ],
    )
    assert values["form"]["value"] == "분말"
    assert warnings == []


def test_model_evidence_matching_uses_unicode_nfkc_normalization() -> None:
    taxonomy = {
        "categories": [
            {
                "category_id": "c1",
                "facets": [
                    {
                        "facet_id": 1,
                        "name": "form",
                        "order": 1,
                        "values": [
                            {"code": 0, "value": "ALL"},
                            {"code": 1, "value": "ABC"},
                        ],
                    }
                ],
            }
        ]
    }

    values, warnings = _apply_model_result(
        pd.Series({"category_id": "c1", "extra_requirement": "ＡＢＣ 형태"}),
        {"form": {"code": 1}},
        TaxonomyLoader(taxonomy),
        [
            {
                "category_id": "c1",
                "facet_name": "form",
                "mapping_status": "MAPPED",
                "value": "ABC",
            }
        ],
    )

    assert values["form"]["code"] == 1
    assert warnings == []


@pytest.mark.parametrize(
    "requirement",
    [
        "ＡＢＣ 말고 캡슐",
        "ABC 또는 캡슐",
        "avoid ABC",
        "ABC not-please",
    ],
)
def test_model_value_evidence_does_not_override_negative_or_alternative_scope(
    requirement,
) -> None:
    taxonomy = {
        "categories": [
            {
                "category_id": "c1",
                "facets": [
                    {
                        "facet_id": 1,
                        "name": "form",
                        "order": 1,
                        "values": [
                            {"code": 0, "value": "ALL"},
                            {"code": 1, "value": "ABC"},
                            {"code": 2, "value": "캡슐"},
                        ],
                    }
                ],
            }
        ]
    }

    _, warnings = _apply_model_result(
        pd.Series({"category_id": "c1", "extra_requirement": requirement}),
        {"form": {"code": 1}},
        TaxonomyLoader(taxonomy),
    )

    assert any("negative or contrastive" in warning for warning in warnings)


def test_runtime_keeps_product_default_when_requirement_is_unresolved(
    tmp_path, monkeypatch
) -> None:
    taxonomy = {
        "categories": [
            {
                "category_id": "c1",
                "facets": [
                    {
                        "facet_id": 1,
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

    class Labeler:
        call_count = 0
        runtime_seconds = 0.0

        def __init__(self, *args, **kwargs):
            pass

        def classify(self, rows, loader):
            self.call_count += 1
            return {"1": {"form": {"code": 1}}}

    monkeypatch.setattr(runtime_job, "OllamaDemandLabeler", Labeler)
    frame = pd.DataFrame(
        [
            {
                "demand_id": "1",
                "catalog_id": "1",
                "category_id": "c1",
                "extra_requirement": "내일까지 배송해주세요",
            }
        ]
    )
    labeled, _ = run_batch(
        frame,
        tmp_path / "unused.json",
        taxonomy_payload=taxonomy,
        model2_fallback_enabled=False,
    )
    assert labeled.loc[0, "label_status"] == "LABELED"
    assert labeled.loc[0, "label"] == "1"
    assert labeled.loc[0, "label_source"] == "PRODUCT_DEFAULT"
    assert Labeler.call_count == 0


@pytest.mark.parametrize(
    "requirement",
    [
        "분말이 아니라 캡슐을 원해요",
        "분말은 싫고 캡슐로 주세요",
        "분말 또는 캡슐이면 괜찮아요",
        "분말과 캡슐을 모두 원해요",
    ],
)
def test_model_fallback_never_promotes_negative_or_ambiguous_mentions(
    tmp_path, monkeypatch, requirement
) -> None:
    taxonomy = {
        "categories": [
            {
                "category_id": "c1",
                "facets": [
                    {
                        "facet_id": 1,
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

    calls = []

    class Labeler:
        call_count = 0
        runtime_seconds = 0.0

        def __init__(self, *args, **kwargs):
            pass

        def classify(self, rows, loader):
            self.call_count += 1
            calls.extend(rows)
            return {"1": {"form": {"code": 1}}}

    monkeypatch.setattr(runtime_job, "OllamaDemandLabeler", Labeler)
    frame = pd.DataFrame(
        [
            {
                "demand_id": "1",
                "catalog_id": "1",
                "category_id": "c1",
                "extra_requirement": requirement,
            }
        ]
    )
    labeled, _ = run_batch(
        frame,
        tmp_path / "unused.json",
        taxonomy_payload=taxonomy,
        model2_fallback_enabled=True,
    )
    assert labeled.loc[0, "label_status"] == "LABELED"
    assert labeled.loc[0, "label"] == "1"
    assert labeled.loc[0, "fallback_status"] == "REVIEW"
    assert labeled.loc[0, "fallback_warning"] in {
        "negative or contrastive constraints remain parser-owned",
        "multiple values in one facet cannot be represented by a single label",
    }
    assert labeled.loc[0, "constraints"] == "[]"
    assert calls == []


def test_model_fallback_requires_exact_category_facet_coverage(
    tmp_path, monkeypatch
) -> None:
    taxonomy = {
        "categories": [
            {
                "category_id": "c1",
                "facets": [
                    {
                        "facet_id": 1,
                        "name": "form",
                        "order": 1,
                        "values": [
                            {"code": 0, "value": "ALL"},
                            {"code": 1, "value": "분말"},
                        ],
                    },
                    {
                        "facet_id": 2,
                        "name": "taste",
                        "order": 2,
                        "values": [
                            {"code": 0, "value": "ALL"},
                            {"code": 1, "value": "딸기"},
                        ],
                    },
                ],
            }
        ]
    }

    class Labeler:
        call_count = 0
        runtime_seconds = 0.0

        def __init__(self, *args, **kwargs):
            pass

        def classify(self, rows, loader):
            self.call_count += 1
            return {"1": {"form": {"code": 1}}}

    monkeypatch.setattr(runtime_job, "OllamaDemandLabeler", Labeler)
    labeled, _ = run_batch(
        pd.DataFrame(
            [
                {
                    "demand_id": "1",
                    "catalog_id": "1",
                    "category_id": "c1",
                    "extra_requirement": "풍미가 좋으면 좋겠어요",
                }
            ]
        ),
        tmp_path / "unused.json",
        taxonomy_payload=taxonomy,
        model2_fallback_enabled=True,
    )

    assert (
        labeled.loc[0, "fallback_warning"]
        == "LLM facet keys do not match the category taxonomy"
    )
    assert labeled.loc[0, "fallback_status"] == "REVIEW"
    assert labeled.loc[0, "label_status"] == "LABELED"
    assert labeled.loc[0, "label"] == "1-1"


@pytest.mark.parametrize("requirement", ["내일까지 배송해주세요", "캡슐로 주세요"])
def test_model_cannot_assign_a_facet_without_matching_text_evidence(
    requirement,
) -> None:
    taxonomy = {
        "categories": [
            {
                "category_id": "c1",
                "facets": [
                    {
                        "facet_id": 1,
                        "name": "form",
                        "order": 1,
                        "values": [
                            {"code": 0, "value": "ALL"},
                            {"code": 1, "value": "분말", "aliases": ["가루"]},
                            {"code": 2, "value": "캡슐"},
                        ],
                    }
                ],
            }
        ]
    }

    row = pd.Series({"category_id": "c1", "extra_requirement": requirement})
    values, warnings = _apply_model_result(
        row,
        {"form": {"code": 1}},
        TaxonomyLoader(taxonomy),
        [
            {
                "category_id": "c1",
                "facet_name": "form",
                "mapping_status": "MAPPED",
                "value": "분말",
            }
        ],
    )
    assert values["form"]["value"] == "분말"
    assert any("lacks matching text evidence" in warning for warning in warnings)


@pytest.mark.parametrize("model_values", [None, {"code": None, "value": None}])
def test_model_null_facet_values_are_not_treated_as_all(model_values) -> None:
    taxonomy = {
        "categories": [
            {
                "category_id": "c1",
                "facets": [
                    {
                        "facet_id": 1,
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

    _, warnings = _apply_model_result(
        pd.Series({"category_id": "c1", "extra_requirement": "분말"}),
        {"form": model_values},
        TaxonomyLoader(taxonomy),
        [
            {
                "category_id": "c1",
                "facet_name": "form",
                "mapping_status": "MAPPED",
                "value": "분말",
            }
        ],
    )

    assert any("facet value" in warning for warning in warnings)


def test_label_runtime_builds_backend_payload(tmp_path) -> None:
    taxonomy = {
        "categories": [
            {
                "category_id": "c1",
                "facets": [
                    {
                        "name": "form",
                        "order": 1,
                        "values": [
                            {"code": 0, "value": "ALL"},
                            {"code": 1, "value": "분말", "aliases": ["가루"]},
                        ],
                    }
                ],
            }
        ]
    }
    path = tmp_path / "taxonomy.json"
    path.write_text(json.dumps(taxonomy, ensure_ascii=False), encoding="utf-8")
    demands = pd.DataFrame(
        [
            {
                "demand_id": "1",
                "catalog_id": "10",
                "category_id": "c1",
                "extra_requirement": "가루",
                "quantity": "1",
                "is_substitutable": "False",
            }
        ]
    )
    labeled, payload = run_batch(
        demands, path, processed_at="2026-01-01T00:00:00+00:00"
    )
    assert labeled.loc[0, "label"] == "1"
    assert payload["results"][0]["demandId"] == 1


def test_runtime_job_uses_part_a_policy_when_rules_are_provided(tmp_path) -> None:
    taxonomy = {
        "categories": [
            {
                "category_id": "c1",
                "facets": [
                    {
                        "name": "functional_ingredients",
                        "order": 1,
                        "values": [
                            {"code": 0, "value": "ALL"},
                            {"code": 1, "value": "오메가-3"},
                        ],
                    }
                ],
            }
        ]
    }
    path = tmp_path / "taxonomy.json"
    path.write_text(json.dumps(taxonomy, ensure_ascii=False), encoding="utf-8")
    demands = pd.DataFrame(
        [
            {
                "demand_id": "1",
                "catalog_id": "10",
                "category_id": "c1",
                "extra_requirement": "오메가3 함유 제품을 원해요.",
                "is_substitutable": "true",
            }
        ]
    )

    labeled, _ = run_batch(
        demands,
        path,
        rules_path=__import__("pathlib").Path("config/demand_constraint_rules.json"),
        processed_at="2026-01-01T00:00:00+00:00",
    )

    assert labeled.loc[0, "label"] == "1"
    assert labeled.loc[0, "label_status"] == "LABELED"


def test_product_defaults_use_only_explicit_known_product_facets() -> None:
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
                                {"code": 1, "value": "분말", "aliases": ["파우더"]},
                                {"code": 2, "value": "캡슐", "aliases": ["캅셀"]},
                            ],
                        }
                    ],
                }
            ]
        }
    )

    values, warnings = loader.product_defaults(
        "c1",
        [
            {
                "category_id": "c1",
                "facet_name": "form",
                "mapping_status": "MAPPED",
                "value": "캅셀",
            }
        ],
    )

    assert values["form"]["code"] == 2
    assert warnings == []
    values, warnings = loader.product_defaults(
        "c1",
        [
            {
                "category_id": "c1",
                "facet_name": "form",
                "mapping_status": "MAPPED",
                "value": "캅셀",
                "value_code": "1",
            }
        ],
    )
    assert values == {}
    assert warnings == ["product facet code does not match taxonomy: form=캅셀"]


def test_conflicting_product_facet_mapping_does_not_become_all() -> None:
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
                                {"code": 2, "value": "캡슐"},
                            ],
                        }
                    ],
                }
            ]
        }
    )

    values, warnings = loader.product_defaults(
        "c1",
        [
            {
                "category_id": "c1",
                "facet_name": "form",
                "mapping_status": "MAPPED",
                "value": "분말",
            },
            {
                "category_id": "c1",
                "facet_name": "form",
                "mapping_status": "MAPPED",
                "value": "캡슐",
            },
        ],
    )

    assert values == {}
    assert warnings == [
        "product Facet profile duplicates facet: form",
        "conflicting product facet values for facet: form",
    ]


def test_unknown_product_facet_is_not_converted_to_all() -> None:
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

    values, warnings = loader.product_defaults(
        "c1",
        [
            {
                "category_id": "c1",
                "facet_name": "form",
                "mapping_status": "UNKNOWN",
                "value": "",
            }
        ],
    )

    assert values == {}
    assert warnings == ["product facet is not known: form (UNKNOWN)"]


def test_all_taxonomy_value_cannot_be_mapped_as_a_product_value() -> None:
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

    values, warnings = loader.product_defaults(
        "c1",
        [
            {
                "category_id": "c1",
                "facet_name": "form",
                "mapping_status": "MAPPED",
                "value": "ALL",
            }
        ],
    )

    assert values == {}
    assert warnings == ["ALL is not a product Facet value: form=ALL"]


def test_product_defaults_do_not_fall_back_to_root_taxonomy() -> None:
    loader = TaxonomyLoader(
        {
            "facets": [
                {
                    "name": "form",
                    "order": 1,
                    "values": [
                        {"code": 0, "value": "ALL"},
                        {"code": 1, "value": "캡슐"},
                    ],
                }
            ]
        }
    )

    values, warnings = loader.product_defaults("unknown-category", [])

    assert values == {}
    assert warnings == ["taxonomy category not found: unknown-category"]


def test_runtime_product_facet_map_uses_backend_catalog_id_only(tmp_path) -> None:
    path = tmp_path / "product_facets.csv"
    pd.DataFrame(
        [
            {
                "backend_catalog_id": "1990",
                "catalog_id": "catalog-seed-source-1",
                "source_product_id": "source-1",
                "category_id": "c1",
                "facet_name": "form",
                "mapping_status": "UNKNOWN",
                "value": "",
            }
        ]
    ).to_csv(path, index=False)

    result = runtime_job._load_runtime_product_facet_map(path)

    assert set(result) == {"1990"}
    assert result["1990"][0]["source_product_id"] == "source-1"


def test_runtime_does_not_complete_demand_without_original_product_profile() -> None:
    taxonomy = {
        "categories": [
            {
                "category_id": "c1",
                "facets": [
                    {
                        "name": "form",
                        "order": 1,
                        "values": [
                            {"code": 0, "value": "ALL"},
                            {"code": 1, "value": "캡슐"},
                        ],
                    }
                ],
            }
        ]
    }
    demands = pd.DataFrame(
        [
            {
                "demand_id": "1",
                "catalog_id": "1990",
                "category_id": "c1",
                "extra_requirement": "",
                "product_name": "캡슐이란 단어가 있어도 profile 없이는 추정하지 않음",
            }
        ]
    )

    labeled, payload = _run_batch(
        demands, None, taxonomy_payload=taxonomy, product_facet_map={}
    )

    assert labeled.loc[0, "label_status"] == "REVIEW"
    assert labeled.loc[0, "label"] == ""
    assert labeled.loc[0, "facet_values"] == "{}"
    assert labeled.loc[0, "processed_at"] == ""
    assert payload["results"] == []


def test_model_fallback_cannot_complete_demand_without_complete_product_profile(
    monkeypatch,
) -> None:
    taxonomy = {
        "categories": [
            {
                "category_id": "c1",
                "facets": [
                    {
                        "name": "form",
                        "order": 1,
                        "values": [
                            {"code": 0, "value": "ALL"},
                            {"code": 1, "value": "캡슐"},
                        ],
                    },
                    {
                        "name": "taste",
                        "order": 2,
                        "values": [
                            {"code": 0, "value": "ALL"},
                            {"code": 1, "value": "딸기"},
                        ],
                    },
                ],
            }
        ]
    }
    demands = pd.DataFrame(
        [
            {
                "demand_id": "1",
                "catalog_id": "1990",
                "category_id": "c1",
                "extra_requirement": "편하게 먹고 싶어요",
            }
        ]
    )

    def parser_output(frame, *_args, **_kwargs):
        output = frame.copy()
        output["status"] = "PASSTHROUGH"
        output["reasonCodes"] = "[]"
        output["constraints"] = "[]"
        output["effectiveRequirementMode"] = "SEMANTIC_TEXT"
        output["label"] = ""
        output["facet_values"] = "{}"
        return output, {}

    class UnexpectedLabeler:
        def __init__(self, *args, **kwargs):
            raise AssertionError("Model 2 cannot run without a complete baseline")

    monkeypatch.setattr(runtime_job, "run_part_a_batch", parser_output)
    monkeypatch.setattr(runtime_job, "OllamaDemandLabeler", UnexpectedLabeler)
    partial_product_profile = {
        "1990": [
            {
                "backend_catalog_id": "1990",
                "category_id": "c1",
                "facet_name": "form",
                "mapping_status": "MAPPED",
                "value": "캡슐",
            }
        ]
    }

    labeled, payload = _run_batch(
        demands,
        None,
        taxonomy_payload=taxonomy,
        product_facet_map=partial_product_profile,
        model2_fallback_enabled=True,
    )

    assert labeled.loc[0, "label_status"] == "REVIEW"
    assert labeled.loc[0, "label"] == ""
    assert labeled.loc[0, "processed_at"] == ""
    assert payload["results"] == []


def test_product_baseline_label_order_is_taxonomy_order_not_csv_order() -> None:
    loader = TaxonomyLoader(
        {
            "categories": [
                {
                    "category_id": "c1",
                    "facets": [
                        {
                            "name": "ingredient",
                            "order": 1,
                            "values": [
                                {"code": 0, "value": "ALL"},
                                {"code": 1, "value": "유산균"},
                            ],
                        },
                        {
                            "name": "form",
                            "order": 2,
                            "values": [
                                {"code": 0, "value": "ALL"},
                                {"code": 2, "value": "캡슐"},
                            ],
                        },
                    ],
                }
            ]
        }
    )

    defaults, warnings = loader.product_defaults(
        "c1",
        [
            {
                "category_id": "c1",
                "facet_name": "form",
                "mapping_status": "MAPPED",
                "value": "캡슐",
            },
            {
                "category_id": "c1",
                "facet_name": "ingredient",
                "mapping_status": "MAPPED",
                "value": "유산균",
            },
        ],
    )

    assert list(defaults) == ["ingredient", "form"]
    assert loader.encode(defaults) == "1-2"
    assert warnings == []


def test_runtime_does_not_convert_unknown_product_facet_to_all() -> None:
    taxonomy = {
        "categories": [
            {
                "category_id": "c1",
                "facets": [
                    {
                        "name": "form",
                        "order": 1,
                        "values": [
                            {"code": 0, "value": "ALL"},
                            {"code": 1, "value": "캡슐"},
                        ],
                    }
                ],
            }
        ]
    }
    demand = pd.DataFrame(
        [
            {
                "demand_id": "1",
                "catalog_id": "1990",
                "category_id": "c1",
                "extra_requirement": "",
            }
        ]
    )
    unknown_profile = {
        "1990": [
            {
                "backend_catalog_id": "1990",
                "category_id": "c1",
                "facet_name": "form",
                "mapping_status": "UNKNOWN",
                "value": "",
            }
        ]
    }

    labeled, payload = _run_batch(
        demand, None, taxonomy_payload=taxonomy, product_facet_map=unknown_profile
    )

    assert labeled.loc[0, "label_status"] == "REVIEW"
    assert labeled.loc[0, "label"] == ""
    assert labeled.loc[0, "processed_at"] == ""
    assert payload["results"] == []


def test_empty_requirement_and_ambiguous_requirement_preserve_product_default(
    tmp_path,
) -> None:
    taxonomy = {
        "categories": [
            {
                "category_id": "c1",
                "facets": [
                    {
                        "name": "form",
                        "order": 1,
                        "facet_id": 1,
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

    for requirement in ("", "분말과 캡슐 모두 괜찮아요"):
        labeled, payload = run_batch(
            pd.DataFrame(
                [
                    {
                        "demand_id": "1",
                        "catalog_id": "10",
                        "category_id": "c1",
                        "extra_requirement": requirement,
                        "product_name": "캡슐형 건강기능식품",
                    }
                ]
            ),
            tmp_path / "unused.json",
            taxonomy_payload=taxonomy,
            product_facet_map={
                "10": [
                    {
                        "catalog_id": "10",
                        "category_id": "c1",
                        "facet_name": "form",
                        "mapping_status": "MAPPED",
                        "value": "캡슐",
                    }
                ]
            },
        )
        assert labeled.loc[0, "label"] == "2"
        assert labeled.loc[0, "label_status"] == "LABELED"
        assert labeled.loc[0, "label_source"] == "PRODUCT_DEFAULT"
        assert str(labeled.loc[0, "processed_at"]).strip()
        assert payload["results"][0]["label"] == "2"
        if requirement:
            assert "UNRESOLVED" in labeled.loc[0, "label_warnings"]


@pytest.mark.parametrize(
    ("status", "reason_codes"),
    [
        ("TAXONOMY_AMBIGUOUS", ["NORMALIZED_VALUE_CODE_COLLISION"]),
        ("REVIEW", ["PARSER_EXCEPTION"]),
        ("REVIEW", ["CONFLICTING_SAME_FACET_VALUES"]),
    ],
)
def test_ambiguous_or_failed_parser_never_calls_model_fallback(
    monkeypatch, status, reason_codes
) -> None:
    class UnexpectedLabeler:
        def __init__(self, *args, **kwargs):
            raise AssertionError("ambiguous/failed analysis must retain the baseline")

    monkeypatch.setattr(runtime_job, "OllamaDemandLabeler", UnexpectedLabeler)
    labeled = pd.DataFrame(
        [
            {
                "demand_id": "1",
                "category_id": "c1",
                "extra_requirement": "분말 또는 캡슐",
                "status": status,
                "effectiveRequirementMode": "NONE",
                "reasonCodes": json.dumps(reason_codes),
                "constraints": "[]",
                "label": "1",
                "facet_values": '{"form":{"code":1,"value":"분말"}}',
                "label_status": "LABELED",
            }
        ]
    )

    result, summary = runtime_job._apply_model2_fallback(
        labeled,
        TaxonomyLoader(
            {
                "categories": [
                    {
                        "category_id": "c1",
                        "facets": [
                            {
                                "name": "form",
                                "values": [
                                    {"code": 0, "value": "ALL"},
                                    {"code": 1, "value": "분말"},
                                ],
                            }
                        ],
                    }
                ]
            }
        ),
        model="test-model",
        endpoint="http://unused",
        timeout=1,
        batch_size=1,
        product_defaults_by_demand={"1": {"form": {"code": 1, "value": "분말"}}},
    )

    assert result.loc[0, "label"] == "1"
    assert result.loc[0, "facet_values"] == '{"form":{"code":1,"value":"분말"}}'
    if status == "TAXONOMY_AMBIGUOUS":
        assert result.loc[0, "fallback_status"] == ""
    else:
        assert result.loc[0, "fallback_status"] == "REVIEW"
        assert "retains product Facet baseline" in result.loc[0, "fallback_warning"]
    assert summary["calls"] == 0


def test_stably_parsed_consumer_facet_overrides_product_default(monkeypatch) -> None:
    taxonomy = {
        "categories": [
            {
                "category_id": "c1",
                "facets": [
                    {
                        "name": "form",
                        "order": 1,
                        "facet_id": 3,
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

    def stable_parser(demands, *_args, **_kwargs):
        output = demands.copy()
        output["status"] = "PARSED"
        output["constraints"] = json.dumps(
            [
                {
                    "facetKey": "form",
                    "canonicalValue": "분말",
                    "facetCode": 3,
                    "valueCode": 1,
                    "constraintType": "PREFER",
                    "evidence": "분말을 원해요",
                }
            ]
        )
        output["reasonCodes"] = "[]"
        output["label"] = "1"
        output["facet_values"] = "{}"
        return output, {}

    monkeypatch.setattr(runtime_job, "run_part_a_batch", stable_parser)
    labeled, payload = run_batch(
        pd.DataFrame(
            [
                {
                    "demand_id": "1",
                    "catalog_id": "10",
                    "category_id": "c1",
                    "extra_requirement": "분말을 원해요",
                    "product_name": "캡슐형 제품",
                }
            ]
        ),
        None,
        taxonomy_payload=taxonomy,
        product_facet_map={
            "10": [
                {
                    "catalog_id": "10",
                    "category_id": "c1",
                    "facet_name": "form",
                    "mapping_status": "MAPPED",
                    "value": "캡슐",
                }
            ]
        },
    )

    assert labeled.loc[0, "label"] == "1"
    assert labeled.loc[0, "label_status"] == "LABELED"
    assert labeled.loc[0, "label_source"] == "PRODUCT_DEFAULT_PLUS_DEMAND"
    assert json.loads(labeled.loc[0, "facet_values"])["form"]["value"] == "분말"
    assert payload["results"][0]["label"] == "1"


def test_validated_llm_positive_value_overrides_only_its_product_facet(
    monkeypatch,
) -> None:
    taxonomy = {
        "categories": [
            {
                "category_id": "c1",
                "facets": [
                    {
                        "name": "form",
                        "order": 1,
                        "facet_id": 3,
                        "values": [
                            {"code": 0, "value": "ALL"},
                            {"code": 1, "value": "분말"},
                            {"code": 2, "value": "캡슐"},
                        ],
                    },
                    {
                        "name": "taste",
                        "order": 2,
                        "facet_id": 4,
                        "values": [
                            {"code": 0, "value": "ALL"},
                            {"code": 1, "value": "딸기"},
                        ],
                    },
                ],
            }
        ]
    }

    def unresolved_parser(demands, *_args, **_kwargs):
        output = demands.copy()
        output["status"] = "PASSTHROUGH"
        output["constraints"] = "[]"
        output["reasonCodes"] = "[]"
        output["effectiveRequirementMode"] = "SEMANTIC_TEXT"
        output["label"] = "0-0"
        output["facet_values"] = "{}"
        return output, {}

    class Labeler:
        call_count = 0

        def __init__(self, *args, **kwargs):
            pass

        def classify(self, rows, loader):
            self.call_count += 1
            return {"1": {"form": {"code": 1}, "taste": {"code": 0}}}

    monkeypatch.setattr(runtime_job, "run_part_a_batch", unresolved_parser)
    monkeypatch.setattr(runtime_job, "OllamaDemandLabeler", Labeler)
    labeled, _ = run_batch(
        pd.DataFrame(
            [
                {
                    "demand_id": "1",
                    "catalog_id": "10",
                    "category_id": "c1",
                    "extra_requirement": "분말 형태가 필요해요",
                    "product_name": "캡슐형 제품",
                }
            ]
        ),
        None,
        taxonomy_payload=taxonomy,
        model2_fallback_enabled=True,
        product_facet_map={
            "10": [
                {
                    "category_id": "c1",
                    "facet_name": "form",
                    "mapping_status": "MAPPED",
                    "value": "캡슐",
                },
                {
                    "category_id": "c1",
                    "facet_name": "taste",
                    "mapping_status": "MAPPED",
                    "value": "딸기",
                },
            ]
        },
    )

    assert labeled.loc[0, "label"] == "1-1"
    assert labeled.loc[0, "label_status"] == "LABELED"
    assert labeled.loc[0, "label_source"] == "PRODUCT_DEFAULT_PLUS_LLM"
    values = json.loads(labeled.loc[0, "facet_values"])
    assert values["form"]["value"] == "분말"
    assert values["taste"]["code"] == 1


def test_backend_response_requires_accepted_status() -> None:
    validate_backend_response({"status": "ACCEPTED", "acceptedCount": 1}, 1)


def test_runtime_does_not_label_or_submit_unknown_category(tmp_path) -> None:
    taxonomy = {
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
    path = tmp_path / "taxonomy.json"
    path.write_text(json.dumps(taxonomy, ensure_ascii=False), encoding="utf-8")
    demands = pd.DataFrame(
        [
            {
                "demand_id": "1",
                "catalog_id": "10",
                "category_id": "unknown",
                "extra_requirement": "분말",
            }
        ]
    )

    labeled, payload = run_batch(
        demands, path, processed_at="2026-01-01T00:00:00+00:00"
    )

    assert labeled.loc[0, "label_status"] == "REVIEW"
    assert labeled.loc[0, "label"] == ""
    assert payload["results"] == []


def test_runtime_job_uses_part_a_parser_for_explicit_requirement() -> None:
    root = __import__("pathlib").Path(".")
    demands = pd.DataFrame(
        [
            {
                "demand_id": "1",
                "catalog_id": "catalog-1",
                "category_id": "health-functional-food:omega_fatty_acid",
                "extra_requirement": "오메가3 함유 제품을 원해요.",
                "is_substitutable": "true",
            }
        ]
    )

    labeled, payload = run_batch(
        demands,
        root / "config/facet_taxonomy_v2_2.json",
        alias_registry_path=root / "config/model1_aliases_reviewed_v2.json",
        compatibility_alias_registry_path=root
        / "config/demand_constraint_aliases.json",
        processed_at="2026-01-01T00:00:00+00:00",
    )

    assert labeled.loc[0, "label"] == "1-2-1"
    assert labeled.loc[0, "label_status"] == "LABELED"
    assert payload["results"][0]["label"] == "1-2-1"


def test_empty_runtime_batch_is_a_successful_noop(tmp_path) -> None:
    taxonomy = {
        "categories": [{"category_id": "c1", "facets": []}],
    }
    path = tmp_path / "taxonomy.json"
    path.write_text(json.dumps(taxonomy), encoding="utf-8")

    labeled, payload = run_batch(
        pd.DataFrame(
            columns=["demand_id", "catalog_id", "category_id", "extra_requirement"]
        ),
        path,
        processed_at="2026-01-01T00:00:00+00:00",
    )

    assert labeled.empty
    assert payload["results"] == []
    assert payload["processedAt"] == "2026-01-01T00:00:00+00:00"


def test_taxonomy_can_be_built_from_database_category_facet() -> None:
    frame = pd.DataFrame(
        [
            {
                "category_id": "health-functional-food:probiotics",
                "category_facet": json.dumps(
                    {
                        "category_id": "health-functional-food:probiotics",
                        "facets": [
                            {
                                "name": "product_form",
                                "order": 1,
                                "values": [
                                    {"code": 0, "value": "ALL"},
                                    {"code": 1, "value": "캡슐"},
                                ],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
            }
        ]
    )

    payload = taxonomy_from_category_facet_rows(frame)

    assert payload["version"] == "backend-category-facet"
    assert (
        payload["categories"][0]["category_id"] == "health-functional-food:probiotics"
    )
