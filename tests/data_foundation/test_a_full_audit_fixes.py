"""A-owned regressions for duplicated routes, experiments and DB checkpoints."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from moongcheap_ai.data_foundation.model1_consensus import (
    gate_observed_candidates,
    select_consensus,
)
from moongcheap_ai.data_foundation import runtime_job
from moongcheap_ai.data_foundation.postgres_writer import write_label_results
from moongcheap_ai.mvp_pipeline import label_batch

ROOT = Path(__file__).resolve().parents[2]
CID = "health-functional-food:vitamin_mineral"


def candidate(value="스텐", copies=1):
    return pd.DataFrame(
        [
            {"name": "재질", "value": value, "source_product_id": str(i)}
            for i in range(copies)
        ]
    )


def test_consensus_duplicate_evidence_does_not_create_independent_votes():
    assert select_consensus([candidate(copies=20)], 3).empty


def test_consensus_preserves_structured_aliases_without_hash_errors():
    frame = candidate().assign(aliases=pd.Series([["스테인리스"]]))
    result = select_consensus([frame, frame, frame], 3)
    assert len(result) == 1
    assert result.iloc[0]["aliases"] == ["스테인리스"]


def test_model1_verifier_cannot_use_generated_draft_as_source():
    sources = [{"source_product_id": "real", "evidence_text": "스텐 텀블러"}]
    frame = pd.DataFrame(
        [
            {
                "name": "재질",
                "value": "스텐",
                "source_product_id": "DRAFT_CANDIDATE",
                "source_text": "스텐",
            },
            {
                "name": "재질",
                "value": "유리",
                "source_product_id": "real",
                "source_text": "스텐 텀블러",
            },
            {
                "name": "재질",
                "value": "스텐",
                "source_product_id": "real",
                "source_text": "스텐 텀블러",
            },
        ]
    )
    assert gate_observed_candidates(frame, sources).index.tolist() == [2]


def test_consensus_no_agreement_never_falls_back_to_first_output():
    assert select_consensus(
        [candidate("스텐"), candidate("유리"), candidate("플라스틱")], 3
    ).empty


def test_consensus_collects_candidates_missing_from_first_generation():
    output = select_consensus(
        [candidate("유리"), candidate("스텐"), candidate("스텐")], 3
    )
    assert set(output.value) == {"스텐"}


@pytest.mark.parametrize("attempts", [2, 3, 4, 5, 6])
def test_consensus_strict_majority_counts_failed_generations(attempts):
    required = attempts // 2 + 1
    assert select_consensus([candidate()] * (required - 1), attempts).empty
    assert not select_consensus([candidate()] * required, attempts).empty


@pytest.mark.parametrize(
    "text, expected",
    [
        ("분말은 싫어요", "2-1-1"),
        ("예시는 분말을 원해요지만 제 요구는 없습니다", "2-1-1"),
        ("정제수로 만든 제품을 원해요", "2-1-1"),
        ("분말 형태를 원해요", "3-1-1"),
        ("", "2-1-1"),
    ],
)
def test_local_a_uses_the_same_runtime_and_backend_profile(tmp_path, text, expected):
    rows = [
        {
            "backend_catalog_id": "10001",
            "category_id": CID,
            "facet_name": name,
            "mapping_status": "MAPPED",
            "value": value,
            "value_code": code,
        }
        for name, value, code in [
            ("product_form", "캡슐", 2),
            ("functional_ingredients", "비타민 C", 1),
            ("daily_frequency", "1일 1회", 1),
        ]
    ]
    path = tmp_path / "profiles.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    output, _ = label_batch(
        pd.DataFrame(
            [
                {
                    "demand_id": "1",
                    "catalog_id": "10001",
                    "category_id": CID,
                    "extra_requirement": text,
                    "is_substitutable": True,
                }
            ]
        ),
        ROOT / "config/facet_taxonomy_v2_2.json",
        ROOT / "config/model1_aliases_reviewed_v2.json",
        product_facets_path=path,
    )
    assert output.iloc[0].label == expected
    assert output.iloc[0].processed_at


def test_gold_contract_compares_facet_code_independently_of_semantics():
    from scripts.evaluation.evaluate_model2_gold_v1 import (
        _constraint_atoms,
        _semantic_atoms,
    )

    expected = [
        {
            "facetKey": "form",
            "facetCode": 1,
            "valueCode": 2,
            "canonicalValue": "캡슐",
            "constraintType": "PREFER",
        }
    ]
    actual = [{**expected[0], "facetCode": 2}]
    assert _semantic_atoms(json.dumps(expected)) == _semantic_atoms(json.dumps(actual))
    assert _constraint_atoms(json.dumps(expected)) != _constraint_atoms(
        json.dumps(actual)
    )


@pytest.mark.parametrize("invalid", ["", "not-json", "{}", "null", "[1]", None])
def test_gold_malformed_constraints_cannot_pass_as_empty(invalid):
    from scripts.evaluation.evaluate_model2_gold_v1 import _constraint_atoms

    with pytest.raises(ValueError):
        _constraint_atoms(invalid)


def mock_checkpoint(monkeypatch, *, fail_at=None):
    calls = []
    writes = []

    def run(frame, taxonomy, **kwargs):
        calls.append(frame.demand_id.tolist())
        if len(calls) == fail_at:
            raise RuntimeError("simulated model failure")
        labeled = frame.assign(label="1", label_status="LABELED")
        return labeled, {
            "results": [{"demandId": value} for value in frame.demand_id],
            "processedAt": kwargs["processed_at"],
        }

    def write(connection, rows, **kwargs):
        writes.append([row["demand_id"] for row in rows])
        return len(rows)

    monkeypatch.setattr(runtime_job, "run_batch", run)
    monkeypatch.setattr(runtime_job, "write_label_results", write)
    return calls, writes


def test_checkpoint_conserves_rows_and_writes_every_completed_chunk(monkeypatch):
    calls, writes = mock_checkpoint(monkeypatch)
    frame = pd.DataFrame({"demand_id": [str(i) for i in range(1, 102)]})
    output, payload = runtime_job.run_checkpointed_batch(
        frame, None, connection=object(), chunk_size=5
    )
    assert (
        len(output)
        == len(payload["results"])
        == payload["checkpointUpdatedCount"]
        == 101
    )
    assert payload["deferredRows"] == 0
    assert calls == writes
    assert len(calls) == 21


def test_checkpoint_keeps_committed_progress_on_later_failure(monkeypatch):
    _, writes = mock_checkpoint(monkeypatch, fail_at=2)
    with pytest.raises(RuntimeError):
        runtime_job.run_checkpointed_batch(
            pd.DataFrame({"demand_id": ["1", "2", "3"]}),
            None,
            connection=object(),
            chunk_size=2,
        )
    assert writes == [["1", "2"]]


def test_checkpoint_time_budget_leaves_unstarted_rows_pending(monkeypatch):
    calls, writes = mock_checkpoint(monkeypatch)
    clock = iter([0, 0, 20])
    monkeypatch.setattr(runtime_job.time, "monotonic", lambda: next(clock))
    output, payload = runtime_job.run_checkpointed_batch(
        pd.DataFrame({"demand_id": ["1", "2", "3"]}),
        None,
        connection=object(),
        chunk_size=2,
        time_budget_seconds=10,
    )
    assert output.demand_id.tolist() == ["1", "2"]
    assert payload["deferredRows"] == 1
    assert calls == writes == [["1", "2"]]


def test_writer_guards_input_snapshot_without_new_update_permissions():
    class Connection:
        rowcount = 0

        def cursor(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, sql, params):
            self.sql, self.params = sql, params

        def commit(self):
            self.committed = True

        def rollback(self):
            raise AssertionError("unexpected rollback")

    connection = Connection()
    assert (
        write_label_results(
            connection,
            [
                {
                    "demand_id": "1",
                    "catalog_id": "10",
                    "extra_requirement": "분말",
                    "label": "3",
                    "label_status": "LABELED",
                }
            ],
            processed_at="2026-10-04T00:00:00Z",
        )
        == 0
    )
    assert "catalog_id::text = %(snapshot_catalog_id)s" in connection.sql
    assert "COALESCE(extra_requirement, '')" in connection.sql
    assert connection.params["snapshot_extra_requirement"] == "분말"


def test_checkpoint_rejects_duplicate_ids_before_any_write(monkeypatch):
    calls, writes = mock_checkpoint(monkeypatch)
    with pytest.raises(ValueError, match="unique positive"):
        runtime_job.run_checkpointed_batch(
            pd.DataFrame({"demand_id": ["1", "2", "1"]}),
            None,
            connection=object(),
            chunk_size=1,
        )
    assert not calls and not writes


def test_release_hashes_match_docker_and_a_jenkins_guards():
    import hashlib

    docker = (ROOT / "docker/Dockerfile.a-labeling").read_text()
    jenkins = (ROOT / "Jenkinsfile").read_text()
    digest = hashlib.sha256(
        (ROOT / "config/facet_taxonomy_v2_2.json").read_bytes()
    ).hexdigest()
    assert digest in docker and digest in jenkins
    assert "io.moongcheap.a.product-facets-sha256" in docker
    assert "EXISTING_PROFILE_SHA" in jenkins
    assert "file.startsWith('tests/data_foundation/')" in jenkins


@pytest.mark.parametrize("path", [
    "tests/test_labeling.py", "tests/model1/test_multisource_facet_discovery.py",
    "tests/test_part_a_b_handoff.py", "tests/deployment/test_a_labeling_manifests.py",
    "scripts/labeling/run_part_a_runtime.py", "scripts/demand/run_demand_5000_model2.py",
    "scripts/evaluation/build_model1_facet_gold.py", "scripts/evaluation/finalize_part_a_gold_v2_2.py",
])
def test_a_test_and_script_only_changes_are_selected_by_jenkins(path):
    import re
    jenkins = (ROOT / "Jenkinsfile").read_text()
    block = re.search(r"env.BUILD_LABELING = files.any \{(.*?)\} \? 'true' : 'false'", jenkins, re.S).group(1)
    prefixes = re.findall(r"file.startsWith\(\s*'([^']+)'\s*\)", block)
    exact = re.findall(r"file\s*==\s*'([^']+)'", block)
    assert path in exact or any(path.startswith(prefix) for prefix in prefixes)


def test_gold_alignment_preserves_original_semantics_and_challenge(tmp_path):
    from scripts.evaluation.evaluate_model2_gold_v1 import align_gold_codes

    source = tmp_path / "source"
    source.mkdir()
    expected = [
        {
            "facetKey": "form",
            "facetCode": 99,
            "valueCode": 99,
            "canonicalValue": "캡슐",
            "constraintType": "PREFER",
        }
    ]
    pd.DataFrame(
        [
            {
                "demand_id": "1",
                "category_id": "c",
                "review_decision": "APPROVE",
                "corrected_expected_constraints": json.dumps(expected),
            }
        ]
    ).to_csv(source / "model2_gold_supported_v1.csv", index=False)
    challenge = source / "model2_gold_out_of_taxonomy_v1.csv"
    challenge.write_bytes(b"demand_id\n2\n")
    taxonomy = tmp_path / "taxonomy.json"
    taxonomy.write_text(
        json.dumps(
            {
                "version": "test",
                "categories": [
                    {
                        "category_id": "c",
                        "facets": [
                            {
                                "name": "form",
                                "facet_id": 1,
                                "order": 1,
                                "values": [
                                    {"value": "ALL", "code": 0},
                                    {"value": "캡슐", "code": 2},
                                ],
                            }
                        ],
                    }
                ],
            }
        )
    )
    before = (source / "model2_gold_supported_v1.csv").read_bytes()
    target = align_gold_codes(source, taxonomy, tmp_path / "aligned")
    assert (source / "model2_gold_supported_v1.csv").read_bytes() == before
    row = pd.read_csv(target / "model2_gold_supported_v1.csv").iloc[0]
    corrected = json.loads(row.corrected_expected_constraints)
    assert corrected == [{**expected[0], "facetCode": 1, "valueCode": 2}]
    assert row.review_decision == "APPROVE"
    assert (target / challenge.name).read_bytes() == challenge.read_bytes()
    with pytest.raises(ValueError):
        align_gold_codes(source, taxonomy, source)


@pytest.mark.parametrize("bad", [True, 1.5, 0, -1])
@pytest.mark.parametrize("field", ["chunk_size", "time_budget_seconds"])
def test_checkpoint_rejects_invalid_integer_configuration(monkeypatch, field, bad):
    calls, writes = mock_checkpoint(monkeypatch)
    with pytest.raises(ValueError):
        runtime_job.run_checkpointed_batch(
            pd.DataFrame({"demand_id": ["1"]}), None,
            connection=object(), **{field: bad},
        )
    assert calls == writes == []


def test_checkpoint_reserves_recursive_retries_even_with_single_row_pages(monkeypatch):
    timeouts = []
    mock_checkpoint(monkeypatch)
    original = runtime_job.run_batch

    def capture(frame, taxonomy, **kwargs):
        timeouts.append(kwargs["llm_timeout"])
        return original(frame, taxonomy, **kwargs)

    monkeypatch.setattr(runtime_job, "run_batch", capture)
    runtime_job.run_checkpointed_batch(
        pd.DataFrame({"demand_id": ["1", "2", "3", "4", "5"]}),
        None, connection=object(), chunk_size=5, time_budget_seconds=60,
        llm_model="test", llm_retries=2, llm_max_rows=1,
        model2_fallback_enabled=True,
    )
    assert timeouts == [1]


def test_checkpoint_missing_id_column_is_explicit_before_writes(monkeypatch):
    calls, writes = mock_checkpoint(monkeypatch)
    with pytest.raises(ValueError, match="demand_id"):
        runtime_job.run_checkpointed_batch(
            pd.DataFrame({"catalog_id": ["1"]}), None, connection=object(),
        )
    assert calls == writes == []


def test_writer_checks_native_category_snapshot_but_not_legacy_mapping():
    queries = []

    class Database:
        rowcount = 0
        def cursor(self): return self
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, query, params): queries.append((query, params))
        def commit(self): pass
        def rollback(self): pass

    row = dict(demand_id="1", catalog_id="2", extra_requirement="", label="1",
               label_status="LABELED", category_snapshot_from_db=True,
               category_db_id="3", category_facet={"facets": []})
    assert write_label_results(Database(), [row], processed_at="2026-10-04T00:00:00Z") == 0
    assert "c.facet::jsonb" in queries[-1][0]
    assert json.loads(queries[-1][1]["snapshot_category_facet"]) == {"facets": []}
    row["category_snapshot_from_db"] = False
    write_label_results(Database(), [row], processed_at="2026-10-04T00:00:00Z")
    assert "pc.category_id" not in queries[-1][0]
