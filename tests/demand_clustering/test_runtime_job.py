from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import quote

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
        "version": "v2.1",
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

    seed_rows = []
    for catalog_id, name in (
        (101, "원상품 보드 상품"),
        (202, "대체 후보 상품"),
        (303, "대체 요청 원상품"),
    ):
        seed_rows.append({
            "catalog_seed_id": f"catalog-seed-domeggook-{catalog_id}",
            "source_product_id": str(catalog_id),
            "name": name,
            "category_seed_id": "cat-v5-protein",
            "source_category_path": "식품 > 건강식품 > 단백질",
            "source_category_id": CATEGORY,
            "status": "ACTIVE",
        })
    seed_path = tmp_path / "product_catalog_seed_v5.csv"
    pd.DataFrame(seed_rows).to_csv(seed_path, index=False)

    model_path = tmp_path / "e5-model"
    model_path.mkdir()
    return {
        "seed": seed_path,
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
        "DEMAND_CATALOG_SEED_PATH": str(paths["seed"]),
        "DEMAND_TAXONOMY_PATH": str(paths["taxonomy"]),
        "DEMAND_CONSTRAINT_RULES_PATH": str(
            ROOT / "config/demand_constraint_rules.json"
        ),
        "DEMAND_CONSTRAINT_COMPAT_ALIASES_PATH": str(
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
        "catalog_name": {
            101: "원상품 보드 상품",
            202: "대체 후보 상품",
            303: "대체 요청 원상품",
        }[catalog_id],
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
        "catalog_name": {
            101: "원상품 보드 상품",
            202: "대체 후보 상품",
            303: "대체 요청 원상품",
        }[catalog_id],
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


@pytest.mark.parametrize("shared_url", [None, "", "  "])
def test_builds_database_dsn_from_backend_credentials(tmp_path, shared_url):
    conninfo_to_dict = pytest.importorskip("psycopg.conninfo").conninfo_to_dict
    environment = _environment(tmp_path)
    del environment["SHARED_DATABASE_URL"]
    if shared_url is not None:
        environment["SHARED_DATABASE_URL"] = shared_url
    environment.update({
        "DB_URL": "jdbc:postgresql://postgres:5432/moongcheap?sslmode=require",
        "DB_USERNAME": " app:@/한% ",
        "DB_PASSWORD": " p@ss:/?#%+&한글 ",
    })

    config = load_job_config(environment)

    # Use the actual driver's parser: encoded credentials must round-trip exactly.
    assert conninfo_to_dict(config.database_url) == {
        "host": "postgres", "port": "5432", "dbname": "moongcheap",
        "user": environment["DB_USERNAME"], "password": environment["DB_PASSWORD"],
        "sslmode": "require",
    }


@pytest.mark.parametrize("url", [
    "jdbc:postgresql://[::1]:5432/moongcheap",
    "postgresql://[::1]:5432/moongcheap",
    "postgres://[::1]:5432/moongcheap",
])
def test_backend_database_url_supports_ipv6_and_native_postgres(tmp_path, url):
    conninfo_to_dict = pytest.importorskip("psycopg.conninfo").conninfo_to_dict
    environment = _environment(tmp_path)
    del environment["SHARED_DATABASE_URL"]
    environment.update({"DB_URL": url, "DB_USERNAME": "app", "DB_PASSWORD": "pass"})

    parsed = conninfo_to_dict(load_job_config(environment).database_url)

    assert parsed["host"] == "::1"
    assert parsed["port"] == "5432"
    assert parsed["user"] == "app"


def test_explicit_shared_database_url_takes_precedence(tmp_path):
    environment = _environment(tmp_path)
    environment.update({"DB_URL": "invalid", "DB_USERNAME": "", "DB_PASSWORD": ""})

    assert load_job_config(environment).database_url == environment["SHARED_DATABASE_URL"]


@pytest.mark.parametrize("missing", ["DB_URL", "DB_USERNAME", "DB_PASSWORD"])
@pytest.mark.parametrize("value", [None, ""])
def test_backend_database_credentials_require_all_three_values(tmp_path, missing, value):
    environment = _environment(tmp_path)
    del environment["SHARED_DATABASE_URL"]
    environment.update({
        "DB_URL": "jdbc:postgresql://postgres/moongcheap",
        "DB_USERNAME": "app", "DB_PASSWORD": "pass",
    })
    if value is None:
        del environment[missing]
    else:
        environment[missing] = value

    with pytest.raises(ConfigurationError, match=missing):
        load_job_config(environment)


@pytest.mark.parametrize("url", [
    "jdbc:mysql://postgres:5432/moongcheap",
    "jdbc:postgresql:///moongcheap",
    "jdbc:postgresql://postgres:invalid/moongcheap",
    "jdbc:postgresql://postgres:70000/moongcheap",
    "jdbc:postgresql://postgres:0/moongcheap",
    "jdbc:postgresql://[broken/moongcheap",
    "jdbc:postgresql://postgres/",
    "jdbc:postgresql://postgres/moongcheap#fragment",
    "jdbc:postgresql://app:embedded-secret@postgres/moongcheap",
    "jdbc:postgresql://postgres/moongcheap?password=embedded-secret",
    "jdbc:postgresql://postgres/moongcheap?user=another-user",
])
def test_invalid_backend_database_url_fails_without_exposing_values(tmp_path, capsys, url):
    environment = _environment(tmp_path)
    del environment["SHARED_DATABASE_URL"]
    environment.update({
        "DB_URL": url, "DB_USERNAME": "private-user", "DB_PASSWORD": "private-password",
    })

    def must_not_run(*args, **kwargs):
        pytest.fail("invalid database configuration must stop before the batch runs")

    assert main([], environ=environment, job_runner=must_not_run) == 2
    output = capsys.readouterr()
    assert not output.out
    payload = json.loads(output.err)
    assert payload["status"] == "CONFIGURATION_ERROR"
    assert "DB_URL" in payload["message"]
    for value in (url, "private-user", "private-password", "embedded-secret"):
        assert value not in output.err


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


def test_rejects_configured_missing_a_alias_file(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    environment["DEMAND_CONSTRAINT_ALIASES_PATH"] = str(
        tmp_path / "missing-a-aliases.json"
    )

    with pytest.raises(
        ConfigurationError,
        match="DEMAND_CONSTRAINT_ALIASES_PATH must reference an existing file",
    ):
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
        catalog_seed_path=paths["seed"],
        taxonomy_path=paths["taxonomy"],
        constraint_rules_path=ROOT / "config/demand_constraint_rules.json",
        constraint_aliases_path=None,
        constraint_compat_aliases_path=ROOT / "config/demand_constraint_aliases.json",
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
        assert request["ruleVersion"] == "substitute-admission-v3-catalog-seed"
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
    assert result.part_a_integration["aliasMode"] == "B_ONLY"
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


def test_user_added_catalog_still_runs_base_formation_and_skips_substitution(
    tmp_path: Path,
) -> None:
    paths = _artifact_paths(tmp_path)
    config = DemandClusteringJobConfig(
        database_url="postgresql://reader:secret@postgres:5432/moongcheap",
        backend_base_url="http://backend:8080",
        backend_internal_key="service-secret",
        catalog_seed_path=paths["seed"],
        taxonomy_path=paths["taxonomy"],
        constraint_rules_path=ROOT / "config/demand_constraint_rules.json",
        constraint_aliases_path=None,
        constraint_compat_aliases_path=(
            ROOT / "config/demand_constraint_aliases.json"
        ),
        e5=E5RuntimeScorerConfig(paths["model"], batch_size=8),
        min_participants=5,
    )
    new_demand = {
        **_demand_row(1, 101),
        "catalog_id": 999,
        "catalog_name": "사용자 추가 상품",
    }
    new_board = {
        **_board_row(31, 101, participant_count=5),
        "catalog_id": 999,
        "catalog_name": "사용자 추가 상품",
    }
    connection = FakeConnection([
        [new_demand],
        [new_board],
        [],
        [new_demand],
        [new_board],
        [],
    ])

    def post_formation(base_url, key, request):
        assert request["existingBoardAssignments"] == [{
            "demandBoardId": 31,
            "demandIds": [1],
        }]
        return BackendBoardPlanApplyResult("APPLIED", 1, 0, ())

    def post_substitute(base_url, key, request):
        assert request["proposals"] == []
        return BackendPlanApplyResult("APPLIED", 0, 0, 0)

    result = run_demand_clustering_job(
        config,
        planned_at=PLANNED_AT,
        connection_factory=lambda database_url, timeout: connection,
        formation_plan_poster=post_formation,
        substitute_plan_poster=post_substitute,
    )

    assert result.execution.formation_request["existingBoardAssignments"]
    assert result.execution.substitute_request["proposals"] == []


def test_unknown_seed_category_stops_before_database_or_backend(tmp_path):
    environment = _environment(tmp_path)
    seed = pd.read_csv(environment["DEMAND_CATALOG_SEED_PATH"], dtype=str)
    seed["source_category_id"] = "unknown-category"
    seed.to_csv(environment["DEMAND_CATALOG_SEED_PATH"], index=False)
    config = load_job_config(environment)

    def must_not_connect(*args):
        pytest.fail("unknown category must be detected before database access")

    with pytest.raises(ValueError, match="taxonomy is missing category"):
        run_demand_clustering_job(config, planned_at=PLANNED_AT, connection_factory=must_not_connect)


def test_empty_seed_stops_before_database_or_backend(tmp_path):
    environment = _environment(tmp_path)
    seed_path = Path(environment["DEMAND_CATALOG_SEED_PATH"])
    seed = pd.read_csv(seed_path, dtype=str)
    seed.iloc[0:0].to_csv(seed_path, index=False)
    config = load_job_config(environment)

    def must_not_connect(*args):
        pytest.fail("empty seed must be detected before database access")

    with pytest.raises(ValueError, match="catalog seed must not be empty"):
        run_demand_clustering_job(
            config,
            planned_at=PLANNED_AT,
            connection_factory=must_not_connect,
        )


@pytest.mark.parametrize("primary_path", [None, ""])
def test_a_path_is_optional_b_base_is_required(tmp_path, primary_path):
    environment = _environment(tmp_path)
    if primary_path is not None:
        environment["DEMAND_CONSTRAINT_ALIASES_PATH"] = primary_path
    config = load_job_config(environment)
    assert config.constraint_aliases_path == (Path(primary_path) if primary_path else None)
    assert config.constraint_compat_aliases_path == ROOT / "config/demand_constraint_aliases.json"
    del environment["DEMAND_CONSTRAINT_COMPAT_ALIASES_PATH"]
    with pytest.raises(ConfigurationError, match="DEMAND_CONSTRAINT_COMPAT_ALIASES_PATH"):
        load_job_config(environment)


@pytest.mark.parametrize("target", [{"code": 999, "value": "정"}, {"code": 1, "value": "캡슐"}])
def test_invalid_a_target_stops_before_database_or_backend(tmp_path, target):
    environment = _environment(tmp_path)
    aliases_path = tmp_path / "invalid-a.json"
    aliases_path.write_text(json.dumps({
        "version": "a-test", "taxonomy_version": "v2.1", "aliases": [{
            "facet_name": "product_form", "canonical_value": "tablet", "surfaces": ["정제"],
            "category_local_values": {CATEGORY: target},
        }],
    }))
    environment["DEMAND_CONSTRAINT_ALIASES_PATH"] = str(aliases_path)
    config = load_job_config(environment)

    def must_not_connect(*args):
        pytest.fail("invalid A target reached database")

    with pytest.raises(ValueError, match="primary alias code"):
        run_demand_clustering_job(config, planned_at=PLANNED_AT, connection_factory=must_not_connect)


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


def test_main_redacts_composed_dsn_and_raw_or_encoded_database_password(tmp_path, capsys):
    environment = _environment(tmp_path)
    del environment["SHARED_DATABASE_URL"]
    password = " db@password:/?#%+ "
    environment.update({
        "DB_URL": "jdbc:postgresql://postgres/moongcheap",
        "DB_USERNAME": "app", "DB_PASSWORD": password,
    })

    def fail(config, **kwargs):
        raise RuntimeError(
            f"{config.database_url} | {password} | {quote(password, safe='')} | "
            f"{config.backend_internal_key}"
        )

    assert main([], environ=environment, job_runner=fail) == 1
    output = capsys.readouterr()
    assert not output.out
    assert password not in output.err
    assert quote(password, safe="") not in output.err
    assert "service-secret" not in output.err
    assert json.loads(output.err)["message"].count("[REDACTED]") == 4
