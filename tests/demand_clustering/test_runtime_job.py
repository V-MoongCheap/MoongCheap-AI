from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest

from moongcheap_ai.demand_clustering.backend_board_plan import (
    BackendBoardPlanApplyResult,
)
from moongcheap_ai.demand_clustering.backend_plan_client import (
    BackendPlanApplyResult,
)
from moongcheap_ai.demand_clustering.e5_runtime_scorer import (
    E5RuntimeScorerConfig,
)
from moongcheap_ai.demand_clustering.runtime_job import (
    ConfigurationError,
    DemandClusteringJobConfig,
    load_job_config,
    main,
    open_read_only_postgres,
    run_demand_clustering_job,
)


ROOT = Path(__file__).parents[2]
NOW = datetime.fromisoformat("2026-09-08T12:34:56+09:00")
PLANNED_AT = NOW
CATEGORY = "health-functional-food:protein"


def _artifact_paths(tmp_path: Path) -> dict[str, Path]:
    taxonomy = {
        "taxonomy_version": "v2.1",
        "categories": [{
            "category_id": CATEGORY,
            "facets": [
                {
                    "name": "product_form",
                    "values": [
                        {"code": 0, "value": "ALL", "aliases": []},
                        {"code": 1, "value": "정", "aliases": []},
                    ],
                },
                {
                    "name": "functional_ingredients",
                    "values": [
                        {"code": 0, "value": "ALL", "aliases": []},
                        {"code": 1, "value": "단백질", "aliases": []},
                    ],
                },
                {
                    "name": "daily_frequency",
                    "values": [
                        {"code": 0, "value": "ALL", "aliases": []},
                        {"code": 1, "value": "1일 1회", "aliases": []},
                    ],
                },
            ],
        }],
    }
    taxonomy_path = tmp_path / "taxonomy.json"
    taxonomy_path.write_text(
        json.dumps(taxonomy, ensure_ascii=False),
        encoding="utf-8",
    )

    profile_rows = []
    for catalog_id, name in (
        (101, "원상품 보드 상품"),
        (202, "대체 후보 상품"),
        (303, "대체 요청 원상품"),
    ):
        profile_rows.append({
            "catalog_id": str(catalog_id),
            "product_name": name,
            "service_category_id": CATEGORY,
            "taxonomy_version": "v2.1",
            "product_form": "정",
            "functional_ingredients_json": '["단백질"]',
            "main_functionality_claim_ids_json": '["protein"]',
            "main_functionality_claim_texts_json": '["단백질 보충"]',
            "intake_method_text": "1일 1회 섭취",
            "profile_status": "EVIDENCE_READY",
        })
    profiles_path = tmp_path / "profiles.csv"
    pd.DataFrame(profile_rows).to_csv(profiles_path, index=False)

    model_path = tmp_path / "e5-model"
    model_path.mkdir()
    return {
        "profiles": profiles_path,
        "taxonomy": taxonomy_path,
        "model": model_path,
    }


def _environment(tmp_path: Path) -> dict[str, str]:
    paths = _artifact_paths(tmp_path)
    return {
        "SHARED_DATABASE_URL": (
            "postgresql://reader:secret@postgres:5432/moongcheap"
        ),
        "BACKEND_BASE_URL": "http://backend:8080/",
        "BACKEND_INTERNAL_KEY": "service-secret",
        "MFDS_CATALOG_PROFILES_PATH": str(paths["profiles"]),
        "DEMAND_TAXONOMY_PATH": str(paths["taxonomy"]),
        "DEMAND_CONSTRAINT_RULES_PATH": str(
            ROOT / "config/demand_constraint_rules.json"
        ),
        "DEMAND_CONSTRAINT_ALIASES_PATH": str(
            ROOT / "config/demand_constraint_aliases.json"
        ),
        "E5_MODEL_PATH": str(paths["model"]),
        "E5_BATCH_SIZE": "8",
        "CLUSTER_MIN_PARTICIPANTS": "5",
        "BACKEND_HTTP_TIMEOUT_SECONDS": "12",
        "POSTGRES_CONNECT_TIMEOUT_SECONDS": "7",
    }


def _demand_row(
    demand_id: int,
    catalog_id: int,
    *,
    extra_requirement: str = "",
) -> dict[str, Any]:
    return {
        "id": demand_id,
        "demand_board_id": None,
        "catalog_id": catalog_id,
        "desired_price_min": 10_001,
        "desired_price_max": 20_000,
        "quantity": 1,
        "extra_requirement": extra_requirement,
        "is_substitutable": True,
        "status": "UNASSIGNED",
        "label": None,
        "desire_end_at": PLANNED_AT + timedelta(days=1),
        "processed_at": None,
        "created_at": PLANNED_AT - timedelta(hours=1),
        "updated_at": PLANNED_AT - timedelta(hours=1),
    }


def _board_row(
    board_id: int,
    catalog_id: int,
    *,
    participant_count: int,
) -> dict[str, Any]:
    return {
        "id": board_id,
        "catalog_id": catalog_id,
        "participant_count": participant_count,
        "price_min": 10_001,
        "price_max": 20_000,
        "status": "GB_GATHERING",
        "sale_end_at": PLANNED_AT + timedelta(days=2),
        "created_at": PLANNED_AT - timedelta(hours=1),
    }


class SequentialCursor:
    def __init__(self, datasets: list[list[dict[str, Any]]]) -> None:
        self._datasets = datasets
        self._index = -1
        self.description = None
        self.executions: list[tuple[str, dict[str, Any]]] = []

    def __enter__(self) -> SequentialCursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, query: str, params: dict[str, Any]) -> None:
        self._index += 1
        self.executions.append((query, params))

    def fetchall(self) -> list[dict[str, Any]]:
        return self._datasets[self._index]


class FakeConnection:
    def __init__(self, datasets: list[list[dict[str, Any]]]) -> None:
        self.cursor_instance = SequentialCursor(datasets)
        self.closed = False

    def cursor(self) -> SequentialCursor:
        return self.cursor_instance

    def close(self) -> None:
        self.closed = True


def test_loads_runtime_config_without_exposing_secret_values(
    tmp_path: Path,
) -> None:
    environment = _environment(tmp_path)

    config = load_job_config(environment)

    assert config.backend_base_url == "http://backend:8080"
    assert config.e5.batch_size == 8
    assert config.backend_http_timeout_seconds == 12
    assert config.postgres_connect_timeout_seconds == 7


def test_rejects_jdbc_database_url(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    environment["SHARED_DATABASE_URL"] = (
        "jdbc:postgresql://postgres:5432/moongcheap"
    )

    with pytest.raises(ConfigurationError, match="not a JDBC URL"):
        load_job_config(environment)


def test_requires_parameter_store_key_injected_into_environment(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    del environment["BACKEND_INTERNAL_KEY"]
    environment["BACKEND_SERVICE_TOKEN"] = "legacy-token"
    with pytest.raises(ConfigurationError, match="BACKEND_INTERNAL_KEY"):
        load_job_config(environment)


def test_rejects_backend_base_url_with_api_path(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    environment["BACKEND_BASE_URL"] = "http://backend:8080/api"

    with pytest.raises(ConfigurationError, match="must not contain an API path"):
        load_job_config(environment)


def test_does_not_use_legacy_checkpoint_setting(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    legacy_directory = tmp_path / "old-checkpoints"
    environment["BATCH_STATE_DIR"] = str(legacy_directory)

    config = load_job_config(environment)

    assert not hasattr(config, "batch_state_dir")
    assert not legacy_directory.exists()


def test_opens_autocommit_read_only_postgres(monkeypatch) -> None:
    observed: dict[str, Any] = {}
    connection = SimpleNamespace(autocommit=False)

    def connect(database_url: str, **kwargs: Any) -> object:
        observed.update({"database_url": database_url, **kwargs})
        return connection

    monkeypatch.setitem(
        sys.modules,
        "psycopg",
        SimpleNamespace(connect=connect),
    )

    actual = open_read_only_postgres("postgresql://reader@db/app", 9)

    assert actual is connection
    assert connection.autocommit is True
    assert observed == {
        "database_url": "postgresql://reader@db/app",
        "connect_timeout": 9,
        "options": "-c default_transaction_read_only=on",
    }


@pytest.mark.parametrize(
    ("rejected_board_ids", "expected_board_id"),
    [((), 32), ((32,), 31), ((31, 32), None)],
)
def test_runs_complete_batch_with_fake_postgres_and_backend(
    tmp_path: Path,
    rejected_board_ids: tuple[int, ...],
    expected_board_id: int | None,
) -> None:
    paths = _artifact_paths(tmp_path)
    config = DemandClusteringJobConfig(
        database_url="postgresql://reader:secret@postgres:5432/moongcheap",
        backend_base_url="http://backend:8080",
        backend_internal_key="service-secret",
        catalog_profiles_path=paths["profiles"],
        taxonomy_path=paths["taxonomy"],
        constraint_rules_path=ROOT / "config/demand_constraint_rules.json",
        constraint_aliases_path=ROOT / "config/demand_constraint_aliases.json",
        e5=E5RuntimeScorerConfig(paths["model"], batch_size=8),
        min_participants=5,
    )
    board_101 = _board_row(31, 101, participant_count=5)
    board_202 = _board_row(32, 202, participant_count=10)
    connection = FakeConnection([
        [_demand_row(1, 101), _demand_row(7, 303)],
        [board_101, board_202],
        [],
        [_demand_row(7, 303)],
        [board_101, board_202],
        [
            {"demand_id": 7, "demand_board_id": board_id}
            for board_id in rejected_board_ids
        ],
    ])
    calls: list[str] = []

    def connection_factory(database_url: str, timeout: int) -> FakeConnection:
        assert database_url == config.database_url
        assert timeout == 10
        return connection

    def post_formation(
        backend_base_url: str,
        internal_key: str,
        request: dict[str, Any],
    ) -> BackendBoardPlanApplyResult:
        calls.append("formation")
        assert backend_base_url == config.backend_base_url
        assert internal_key == config.backend_internal_key
        assert request["existingBoardAssignments"] == [{
            "demandBoardId": 31,
            "demandIds": [1],
        }]
        assert request["newBoards"] == []
        return BackendBoardPlanApplyResult(
            status="APPLIED",
            existing_applied_demand_count=1,
            existing_stale_rejected_count=0,
            new_boards=(),
        )

    def post_substitute(
        backend_base_url: str,
        internal_key: str,
        request: dict[str, Any],
    ) -> BackendPlanApplyResult:
        calls.append("substitute")
        assert backend_base_url == config.backend_base_url
        assert internal_key == config.backend_internal_key
        assert request["ruleVersion"] == "substitute-admission-v2"
        expected_proposals = [] if expected_board_id is None else [{
            "demandId": 7,
            "expectedOriginalCatalogId": 303,
            "substituteCatalogId": 202 if expected_board_id == 32 else 101,
            "demandBoardId": expected_board_id,
        }]
        assert request["proposals"] == expected_proposals
        return BackendPlanApplyResult(
            status="APPLIED",
            applied_count=len(expected_proposals),
            already_applied_count=0,
            stale_rejected_count=0,
        )

    result = run_demand_clustering_job(
        config,
        planned_at=PLANNED_AT,
        connection_factory=connection_factory,
        formation_plan_poster=post_formation,
        substitute_plan_poster=post_substitute,
    )

    assert calls == ["formation", "substitute"]
    assert connection.closed is True
    assert len(connection.cursor_instance.executions) == 6
    assert "batchId" not in result.to_dict()
    assert result.e5_cache_summary["modelLoaded"] is False
    assert result.to_dict()["substitution"]["proposalCount"] == (
        0 if expected_board_id is None else 1
    )

    # Even another invocation at the same timestamp must reread current state.
    next_connection = FakeConnection([[], [board_101, board_202]] * 2)

    def empty_formation(base_url, key, request):
        assert request["existingBoardAssignments"] == []
        assert request["newBoards"] == []
        return BackendBoardPlanApplyResult("APPLIED", 0, 0, ())

    def empty_substitution(base_url, key, request):
        assert request["proposals"] == []
        return BackendPlanApplyResult("APPLIED", 0, 0, 0)

    next_result = run_demand_clustering_job(
        config,
        planned_at=PLANNED_AT,
        connection_factory=lambda database_url, timeout: next_connection,
        formation_plan_poster=empty_formation,
        substitute_plan_poster=empty_substitution,
    )
    assert next_connection.closed
    assert len(next_connection.cursor_instance.executions) == 4
    assert next_result.execution.initial_demand_count == 0
    assert next_result.execution.substitute_request["proposals"] == []


@pytest.mark.parametrize("option", ["--batch-id", "--planned-at"])
def test_rejects_obsolete_replay_options(option: str, capsys) -> None:
    def unexpected_runner(*args, **kwargs):
        raise AssertionError("invalid retry must not run")

    with pytest.raises(SystemExit) as error:
        main([option, "old-value"], environ={}, job_runner=unexpected_runner)
    assert error.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err


def test_main_uses_current_time_without_reusing_an_hourly_slot(
    tmp_path: Path,
    capsys,
) -> None:
    environment = _environment(tmp_path)
    observed: dict[str, Any] = {}

    class Result:
        def to_dict(self) -> dict[str, str]:
            return {"status": "OK", "plannedAt": observed["planned_at"].isoformat()}

    def job_runner(config, *, planned_at, event_handler):
        observed.update({
            "config": config,
            "planned_at": planned_at,
            "event_handler": event_handler,
        })
        return Result()

    exit_code = main(
        [],
        environ=environment,
        now=NOW,
        job_runner=job_runner,
    )

    assert exit_code == 0
    assert observed["planned_at"] == NOW
    assert json.loads(capsys.readouterr().out) == {
        "plannedAt": NOW.isoformat(),
        "status": "OK",
    }


def test_main_redacts_runtime_secrets_on_failure(
    tmp_path: Path,
    capsys,
) -> None:
    environment = _environment(tmp_path)

    def job_runner(config, **kwargs):
        raise RuntimeError(
            f"failed with {config.database_url} and "
            f"{config.backend_internal_key}"
        )

    exit_code = main(
        [],
        environ=environment,
        now=NOW,
        job_runner=job_runner,
    )

    error_payload = json.loads(capsys.readouterr().err)
    assert exit_code == 1
    assert error_payload["status"] == "FAILED"
    assert "secret" not in error_payload["message"]
    assert error_payload["message"].count("[REDACTED]") == 2
