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
    run_batch,
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
    assert _first_env(source, "A_LLM_ENDPOINT", "A_MODEL2_OLLAMA_BASE_URL") == "http://127.0.0.1:11434"


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


def test_main_reports_model_preflight_failure_without_opening_database(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setenv("A_LLM_ENABLED", "true")
    monkeypatch.setenv("A_LLM_MODEL", "qwen2.5:7b-instruct")

    def fail_preflight(*args, **kwargs):
        raise LLMLabelingError("Ollama model is not available")

    def database_must_not_open(*args, **kwargs):
        raise AssertionError("DB must not be opened after model preflight failure")

    monkeypatch.setattr(runtime_job, "ensure_ollama_model_available", fail_preflight)
    monkeypatch.setattr(runtime_job, "open_postgres", database_must_not_open)

    code = runtime_job.main(["--write-db", "--output", str(tmp_path / "result.csv")])

    captured = capsys.readouterr()
    assert code == 1
    assert json.loads(captured.err) == {
        "status": "FAILED",
        "error": "Ollama model is not available",
    }
    assert captured.out == ""


@pytest.mark.parametrize(
    ("rows", "results", "message"),
    [
        ([{"demand_id": "1", "category_id": "c1"}], [
            {"demand_id": "1", "facet_values": {}},
            {"demand_id": "1", "facet_values": {}},
        ], "duplicate demand ID"),
        ([{"demand_id": "1", "category_id": "c1"}], [{"demand_id": "extra", "facet_values": {}}], "unexpected demand ID"),
        ([{"demand_id": "1", "category_id": "c1"}, {"demand_id": "2", "category_id": "c1"}], [{"demand_id": "1", "facet_values": {}}], "omitted demand IDs"),
    ],
)
def test_ollama_rejects_duplicate_unexpected_or_missing_result_ids(monkeypatch, rows, results, message) -> None:
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


def test_ollama_rejects_duplicate_or_missing_request_ids_before_http(monkeypatch) -> None:
    def unexpected_http_call(*args, **kwargs):
        raise AssertionError("invalid requests must not be sent")

    monkeypatch.setattr(
        "moongcheap_ai.data_foundation.demand_label_comparison.urllib.request.urlopen",
        unexpected_http_call,
    )
    labeler = OllamaDemandLabeler("test")
    loader = TaxonomyLoader({"categories": []})
    for rows, expected in [
        ([{"demand_id": "1", "category_id": "c1"}, {"demand_id": "1", "category_id": "c1"}], "duplicate demand IDs"),
        ([{"demand_id": " "}], "missing demand_id"),
        ([{}], "missing demand_id"),
        ([{"demand_id": "1"}], "missing category_id"),
    ]:
        with pytest.raises(LLMLabelingError, match=expected):
            labeler.classify(rows, loader)
    assert labeler.call_count == 0


@pytest.mark.parametrize("envelope", [[], None, 3, {"response": "3"}, {"response": "{}"}])
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
    frame = pd.DataFrame([
        {"demand_id": "1", "catalog_id": "10", "category_id": "c1", "label": "1", "facet_values": "{}", "label_status": "LABELED"},
        {"demand_id": "2", "catalog_id": "11", "category_id": "c1", "label": "0", "facet_values": "{}", "label_status": "LABELED_WITH_REVIEW"},
        {"demand_id": "3", "catalog_id": "12", "category_id": "c1", "label": "0", "facet_values": "{}", "label_status": "REVIEW"},
        {"demand_id": "4", "catalog_id": "13", "category_id": "c1", "label": "1", "facet_values": "{}", "label_status": "PARSED"},
    ])

    payload = build_label_result_payload(frame, processed_at="2026-09-26T00:00:00Z")

    assert [row["demandId"] for row in payload["results"]] == [1, 4]


def test_runtime_splits_failed_llm_batches_and_processes_every_row(tmp_path, monkeypatch) -> None:
    taxonomy = {
        "categories": [{
            "category_id": "c1",
            "facets": [{
                "name": "form", "order": 1,
                "values": [{"code": 0, "value": "ALL"}, {"code": 1, "value": "분말"}],
            }],
        }],
    }
    path = tmp_path / "taxonomy.json"
    path.write_text(json.dumps(taxonomy, ensure_ascii=False), encoding="utf-8")
    demands = pd.DataFrame([
        {"demand_id": str(i), "catalog_id": str(i), "category_id": "c1", "extra_requirement": "조건 확인"}
        for i in range(3)
    ])

    class FlakyLabeler:
        call_count = 0

        def __init__(self, *args, **kwargs):
            pass

        def classify(self, rows, loader):
            type(self).call_count += 1
            if len(rows) > 1:
                raise LLMLabelingError("synthetic batch failure")
            return {str(rows[0]["demand_id"]): {"form": {"code": 1}}}

    monkeypatch.setattr(runtime_job, "OllamaDemandLabeler", FlakyLabeler)
    labeled, _ = runtime_job.run_batch(
        demands, path, llm_model="test", llm_batch_size=3, llm_retries=0
    )

    assert len(labeled) == 3
    assert set(labeled["llm_status"]) == {"REVIEW"}
    assert set(labeled["label_status"]) == {"REVIEW"}
    assert FlakyLabeler.call_count > 3


@pytest.mark.parametrize("outcome", ["review", "unavailable"])
def test_first_fallback_decision_is_not_overridden_by_second_call(tmp_path, monkeypatch, outcome) -> None:
    taxonomy = {"categories": [{"category_id": "c1", "facets": [{
        "facet_id": 1, "name": "form", "order": 1,
        "values": [{"code": 0, "value": "ALL"}, {"code": 1, "value": "분말"}],
    }]}]}
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
    frame = pd.DataFrame([{"demand_id": "1", "catalog_id": "1", "category_id": "c1", "extra_requirement": "조건 확인"}])
    labeled, _ = run_batch(frame, tmp_path / "unused.json", taxonomy_payload=taxonomy, model2_fallback_enabled=True)
    assert Labeler.calls == 1
    assert labeled.loc[0, "label_status"] == "REVIEW"
    summary = labeled.attrs["model2_fallback"]
    assert summary["calls"] == 1
    assert summary["applied"] == 0
    assert summary["failed"] == int(outcome == "unavailable")
    assert summary["review"] == int(outcome == "review")


def test_model_value_with_matching_alias_has_positive_evidence() -> None:
    taxonomy = {"categories": [{"category_id": "c1", "facets": [{
        "facet_id": 1, "name": "form", "order": 1,
        "values": [{"code": 0, "value": "ALL"}, {"code": 1, "value": "분말", "aliases": ["가루"]}],
    }]}]}

    row = pd.Series({"category_id": "c1", "extra_requirement": "가루 형태를 원해요"})
    values, warnings = _apply_model_result(row, {"form": {"code": 1}}, TaxonomyLoader(taxonomy))
    assert values["form"]["value"] == "분말"
    assert warnings == []


def test_model_evidence_matching_uses_unicode_nfkc_normalization() -> None:
    taxonomy = {"categories": [{"category_id": "c1", "facets": [{
        "facet_id": 1, "name": "form", "order": 1,
        "values": [{"code": 0, "value": "ALL"}, {"code": 1, "value": "ABC"}],
    }]}]}

    values, warnings = _apply_model_result(
        pd.Series({"category_id": "c1", "extra_requirement": "ＡＢＣ 형태"}),
        {"form": {"code": 1}},
        TaxonomyLoader(taxonomy),
    )

    assert values["form"]["code"] == 1
    assert warnings == []


@pytest.mark.parametrize("requirement", [
    "ＡＢＣ 말고 캡슐",
    "ABC 또는 캡슐",
    "avoid ABC",
    "ABC not-please",
])
def test_model_value_evidence_does_not_override_negative_or_alternative_scope(requirement) -> None:
    taxonomy = {"categories": [{"category_id": "c1", "facets": [{
        "facet_id": 1, "name": "form", "order": 1,
        "values": [{"code": 0, "value": "ALL"}, {"code": 1, "value": "ABC"}, {"code": 2, "value": "캡슐"}],
    }]}]}

    _, warnings = _apply_model_result(
        pd.Series({"category_id": "c1", "extra_requirement": requirement}),
        {"form": {"code": 1}},
        TaxonomyLoader(taxonomy),
    )

    assert any("negative or contrastive" in warning for warning in warnings)


def test_runtime_keeps_model_value_without_text_evidence_in_review(tmp_path, monkeypatch) -> None:
    taxonomy = {"categories": [{"category_id": "c1", "facets": [{
        "facet_id": 1, "name": "form", "order": 1,
        "values": [{"code": 0, "value": "ALL"}, {"code": 1, "value": "분말"}],
    }]}]}

    class Labeler:
        call_count = 0
        runtime_seconds = 0.0

        def __init__(self, *args, **kwargs):
            pass

        def classify(self, rows, loader):
            self.call_count += 1
            return {"1": {"form": {"code": 1}}}

    monkeypatch.setattr(runtime_job, "OllamaDemandLabeler", Labeler)
    frame = pd.DataFrame([{
        "demand_id": "1",
        "catalog_id": "1",
        "category_id": "c1",
        "extra_requirement": "내일까지 배송해주세요",
    }])
    labeled, _ = run_batch(
        frame,
        tmp_path / "unused.json",
        taxonomy_payload=taxonomy,
        model2_fallback_enabled=True,
    )
    assert labeled.loc[0, "label_status"] == "REVIEW"
    assert labeled.loc[0, "fallback_status"] == "REVIEW"


@pytest.mark.parametrize("requirement", [
    "분말이 아니라 캡슐을 원해요",
    "분말은 싫고 캡슐로 주세요",
    "분말 또는 캡슐이면 괜찮아요",
    "분말과 캡슐을 모두 원해요",
])
def test_model_fallback_never_promotes_negative_or_ambiguous_mentions(tmp_path, monkeypatch, requirement) -> None:
    taxonomy = {"categories": [{"category_id": "c1", "facets": [{
        "facet_id": 1, "name": "form", "order": 1,
        "values": [
            {"code": 0, "value": "ALL"},
            {"code": 1, "value": "분말"},
            {"code": 2, "value": "캡슐"},
        ],
    }]}]}

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
    frame = pd.DataFrame([{
        "demand_id": "1", "catalog_id": "1", "category_id": "c1",
        "extra_requirement": requirement,
    }])
    labeled, _ = run_batch(
        frame,
        tmp_path / "unused.json",
        taxonomy_payload=taxonomy,
        model2_fallback_enabled=True,
    )
    assert labeled.loc[0, "label_status"] == "REVIEW"
    assert labeled.loc[0, "fallback_status"] == "REVIEW"
    assert labeled.loc[0, "constraints"] == "[]"
    assert calls == []


def test_model_fallback_requires_exact_category_facet_coverage(tmp_path, monkeypatch) -> None:
    taxonomy = {"categories": [{"category_id": "c1", "facets": [
        {"facet_id": 1, "name": "form", "order": 1, "values": [
            {"code": 0, "value": "ALL"}, {"code": 1, "value": "분말"},
        ]},
        {"facet_id": 2, "name": "taste", "order": 2, "values": [
            {"code": 0, "value": "ALL"}, {"code": 1, "value": "딸기"},
        ]},
    ]}]}

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
        pd.DataFrame([{
            "demand_id": "1", "catalog_id": "1", "category_id": "c1",
            "extra_requirement": "풍미가 좋으면 좋겠어요",
        }]),
        tmp_path / "unused.json",
        taxonomy_payload=taxonomy,
        model2_fallback_enabled=True,
    )

    assert labeled.loc[0, "fallback_status"] == "REVIEW"
    assert labeled.loc[0, "fallback_warning"] == "LLM facet keys do not match the category taxonomy"
    assert labeled.loc[0, "label_status"] == "REVIEW"


@pytest.mark.parametrize("requirement", ["내일까지 배송해주세요", "캡슐로 주세요"])
def test_model_cannot_assign_a_facet_without_matching_text_evidence(requirement) -> None:
    taxonomy = {"categories": [{"category_id": "c1", "facets": [{
        "facet_id": 1, "name": "form", "order": 1,
        "values": [
            {"code": 0, "value": "ALL"},
            {"code": 1, "value": "분말", "aliases": ["가루"]},
            {"code": 2, "value": "캡슐"},
        ],
    }]}]}

    row = pd.Series({"category_id": "c1", "extra_requirement": requirement})
    values, warnings = _apply_model_result(row, {"form": {"code": 1}}, TaxonomyLoader(taxonomy))
    assert values["form"]["value"] == "분말"
    assert any("lacks matching text evidence" in warning for warning in warnings)


@pytest.mark.parametrize("model_values", [None, {"code": None, "value": None}])
def test_model_null_facet_values_are_not_treated_as_all(model_values) -> None:
    taxonomy = {"categories": [{"category_id": "c1", "facets": [{
        "facet_id": 1, "name": "form", "order": 1,
        "values": [{"code": 0, "value": "ALL"}, {"code": 1, "value": "분말"}],
    }]}]}

    _, warnings = _apply_model_result(
        pd.Series({"category_id": "c1", "extra_requirement": "분말"}),
        {"form": model_values},
        TaxonomyLoader(taxonomy),
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
    demands = pd.DataFrame([{
        "demand_id": "1",
        "catalog_id": "catalog-1",
        "category_id": "health-functional-food:omega_fatty_acid",
        "extra_requirement": "오메가3 함유 제품을 원해요.",
        "is_substitutable": "true",
    }])

    labeled, payload = run_batch(
        demands,
        root / "config/facet_taxonomy_v2_2.json",
        alias_registry_path=root / "config/model1_aliases_reviewed_v2.json",
        compatibility_alias_registry_path=root / "config/demand_constraint_aliases.json",
        processed_at="2026-01-01T00:00:00+00:00",
    )

    assert labeled.loc[0, "label"] == "0-2-0"
    assert labeled.loc[0, "label_status"] == "LABELED"
    assert payload["results"][0]["label"] == "0-2-0"


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
