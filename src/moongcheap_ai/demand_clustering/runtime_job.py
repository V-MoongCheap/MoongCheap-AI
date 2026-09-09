"""One-shot production entry point for the hourly clustering batch."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

import pandas as pd
from dotenv import load_dotenv

from ..demand_constraints import DemandConstraintParser
from .backend_board_plan import post_board_assignment_plan
from .backend_plan_client import post_substitute_board_admission_plan
from .batch_execution import (
    BatchEventHandler,
    DemandClusteringBatchExecutionResult,
    FormationPlanPoster,
    SubstitutePlanPoster,
    execute_demand_clustering_batch,
)
from .config import load_min_cluster_participants
from .e5_runtime_scorer import (
    E5RuntimeScorerConfig,
    E5RuntimeTextSimilarityScorer,
)
from .postgres_reader import (
    PostgreSQLClusteringInputReader,
    PostgreSQLConnection,
)
from .substitute_proposal_planner import (
    ClaimIndexedSubstituteProposalPlanner,
)


SHARED_DATABASE_URL_ENV = "SHARED_DATABASE_URL"
BACKEND_BASE_URL_ENV = "BACKEND_BASE_URL"
BACKEND_INTERNAL_KEY_ENV = "BACKEND_INTERNAL_KEY"
MFDS_CATALOG_PROFILES_PATH_ENV = "MFDS_CATALOG_PROFILES_PATH"
DEMAND_TAXONOMY_PATH_ENV = "DEMAND_TAXONOMY_PATH"
DEMAND_CONSTRAINT_RULES_PATH_ENV = "DEMAND_CONSTRAINT_RULES_PATH"
DEMAND_CONSTRAINT_ALIASES_PATH_ENV = "DEMAND_CONSTRAINT_ALIASES_PATH"
BACKEND_HTTP_TIMEOUT_SECONDS_ENV = "BACKEND_HTTP_TIMEOUT_SECONDS"
POSTGRES_CONNECT_TIMEOUT_SECONDS_ENV = "POSTGRES_CONNECT_TIMEOUT_SECONDS"

DEFAULT_BACKEND_HTTP_TIMEOUT_SECONDS = 15
DEFAULT_POSTGRES_CONNECT_TIMEOUT_SECONDS = 10
FORMATION_RULE_VERSION = "board-formation-v1"
SUBSTITUTE_RULE_VERSION = "substitute-admission-v2"
JOB_RESULT_SCHEMA_VERSION = "demand-clustering-job-result.v0.1"


class ConfigurationError(ValueError):
    """The runtime environment cannot safely start a clustering batch."""


class RuntimePostgreSQLConnection(PostgreSQLConnection, Protocol):
    def close(self) -> None: ...


PostgreSQLConnectionFactory = Callable[
    [str, int],
    RuntimePostgreSQLConnection,
]


@dataclass(frozen=True, slots=True)
class DemandClusteringJobConfig:
    database_url: str
    backend_base_url: str
    backend_internal_key: str
    catalog_profiles_path: Path
    taxonomy_path: Path
    constraint_rules_path: Path
    constraint_aliases_path: Path
    e5: E5RuntimeScorerConfig
    min_participants: int
    backend_http_timeout_seconds: int = DEFAULT_BACKEND_HTTP_TIMEOUT_SECONDS
    postgres_connect_timeout_seconds: int = (
        DEFAULT_POSTGRES_CONNECT_TIMEOUT_SECONDS
    )


@dataclass(frozen=True, slots=True)
class DemandClusteringJobResult:
    planned_at: datetime
    execution: DemandClusteringBatchExecutionResult
    e5_cache_summary: Mapping[str, int | bool]

    def to_dict(self) -> dict[str, Any]:
        formation_status_counts = Counter(
            board.status for board in self.execution.formation_result.new_boards
        )
        proposal_count = len(self.execution.substitute_request["proposals"])
        return {
            "schemaVersion": JOB_RESULT_SCHEMA_VERSION,
            "plannedAt": self.planned_at.isoformat(),
            "initialDemandCount": self.execution.initial_demand_count,
            "formation": {
                "status": self.execution.formation_result.status,
                "attemptedDemandCount": len(
                    self.execution.formation_attempted_demand_ids
                ),
                "existingAppliedCount": (
                    self.execution.formation_result
                    .existing_applied_demand_count
                ),
                "existingStaleCount": (
                    self.execution.formation_result
                    .existing_stale_rejected_count
                ),
                "newBoardResultCounts": dict(
                    sorted(formation_status_counts.items())
                ),
            },
            "refreshedDemandCount": self.execution.refreshed_demand_count,
            "substitution": {
                "status": self.execution.substitute_result.status,
                "candidateDemandCount": len(
                    self.execution.substitute_candidate_demand_ids
                ),
                "proposalCount": proposal_count,
                "appliedCount": self.execution.substitute_result.applied_count,
                "alreadyAppliedCount": (
                    self.execution.substitute_result.already_applied_count
                ),
                "staleRejectedCount": (
                    self.execution.substitute_result.stale_rejected_count
                ),
            },
            "e5": dict(self.e5_cache_summary),
        }


def _required_value(source: Mapping[str, str], key: str) -> str:
    value = source.get(key, "").strip()
    if not value:
        raise ConfigurationError(f"{key} must not be empty")
    return value


def _required_file(source: Mapping[str, str], key: str) -> Path:
    path = Path(_required_value(source, key)).expanduser()
    if not path.is_file():
        raise ConfigurationError(f"{key} must reference an existing file")
    return path


def _positive_integer(
    source: Mapping[str, str],
    key: str,
    default: int,
) -> int:
    raw_value = source.get(key, str(default)).strip()
    try:
        value = int(raw_value)
    except ValueError as error:
        raise ConfigurationError(f"{key} must be an integer") from error
    if value < 1:
        raise ConfigurationError(f"{key} must be positive")
    return value


def _backend_base_url(value: str) -> str:
    normalized = value.rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigurationError(
            f"{BACKEND_BASE_URL_ENV} must be an HTTP(S) base URL"
        )
    if parsed.path not in {"", "/"}:
        raise ConfigurationError(
            f"{BACKEND_BASE_URL_ENV} must not contain an API path"
        )
    if parsed.query or parsed.fragment:
        raise ConfigurationError(
            f"{BACKEND_BASE_URL_ENV} must not contain a query or fragment"
        )
    return normalized


def load_job_config(
    environ: Mapping[str, str] | None = None,
) -> DemandClusteringJobConfig:
    """Load injected secrets and artifact settings without querying AWS at runtime.

    Deployment injects the Parameter Store key as BACKEND_INTERNAL_KEY. The
    application does not require AWS credentials or persist mutation requests.
    """

    source = os.environ if environ is None else environ
    database_url = _required_value(source, SHARED_DATABASE_URL_ENV)
    if database_url.startswith("jdbc:"):
        raise ConfigurationError(
            f"{SHARED_DATABASE_URL_ENV} must use a PostgreSQL driver DSN, "
            "not a JDBC URL"
        )
    try:
        e5 = E5RuntimeScorerConfig.from_environment(source)
    except ValueError as error:
        raise ConfigurationError(str(error)) from error
    if not e5.model_path.expanduser().is_dir():
        raise ConfigurationError(
            "E5_MODEL_PATH must reference an existing local model directory"
        )
    try:
        min_participants = load_min_cluster_participants(source)
    except ValueError as error:
        raise ConfigurationError(str(error)) from error

    return DemandClusteringJobConfig(
        database_url=database_url,
        backend_base_url=_backend_base_url(
            _required_value(source, BACKEND_BASE_URL_ENV)
        ),
        backend_internal_key=_required_value(
            source,
            BACKEND_INTERNAL_KEY_ENV,
        ),
        catalog_profiles_path=_required_file(
            source,
            MFDS_CATALOG_PROFILES_PATH_ENV,
        ),
        taxonomy_path=_required_file(source, DEMAND_TAXONOMY_PATH_ENV),
        constraint_rules_path=_required_file(
            source,
            DEMAND_CONSTRAINT_RULES_PATH_ENV,
        ),
        constraint_aliases_path=_required_file(
            source,
            DEMAND_CONSTRAINT_ALIASES_PATH_ENV,
        ),
        e5=E5RuntimeScorerConfig(
            model_path=e5.model_path.expanduser(),
            model_revision=e5.model_revision,
            batch_size=e5.batch_size,
        ),
        min_participants=min_participants,
        backend_http_timeout_seconds=_positive_integer(
            source,
            BACKEND_HTTP_TIMEOUT_SECONDS_ENV,
            DEFAULT_BACKEND_HTTP_TIMEOUT_SECONDS,
        ),
        postgres_connect_timeout_seconds=_positive_integer(
            source,
            POSTGRES_CONNECT_TIMEOUT_SECONDS_ENV,
            DEFAULT_POSTGRES_CONNECT_TIMEOUT_SECONDS,
        ),
    )


def open_read_only_postgres(
    database_url: str,
    connect_timeout_seconds: int,
) -> RuntimePostgreSQLConnection:
    """Open an autocommit connection with server-enforced read-only sessions."""

    try:
        import psycopg
    except ImportError as error:
        raise RuntimeError(
            "PostgreSQL runtime requires psycopg; install the project runtime "
            "dependencies"
        ) from error

    connection = psycopg.connect(
        database_url,
        connect_timeout=connect_timeout_seconds,
        options="-c default_transaction_read_only=on",
    )
    connection.autocommit = True
    return connection


def _load_taxonomy(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError("demand taxonomy must contain valid JSON") from error
    if not isinstance(payload, Mapping):
        raise ValueError("demand taxonomy root must be a JSON object")
    return payload


def _default_formation_poster(
    timeout_seconds: int,
) -> FormationPlanPoster:
    return partial(
        post_board_assignment_plan,
        timeout_seconds=timeout_seconds,
    )


def _default_substitute_poster(
    timeout_seconds: int,
) -> SubstitutePlanPoster:
    return partial(
        post_substitute_board_admission_plan,
        timeout_seconds=timeout_seconds,
    )


def run_demand_clustering_job(
    config: DemandClusteringJobConfig,
    *,
    planned_at: datetime,
    connection_factory: PostgreSQLConnectionFactory = open_read_only_postgres,
    formation_plan_poster: FormationPlanPoster | None = None,
    substitute_plan_poster: SubstitutePlanPoster | None = None,
    event_handler: BatchEventHandler | None = None,
) -> DemandClusteringJobResult:
    """Build all runtime dependencies and execute one complete batch."""

    if planned_at.tzinfo is None or planned_at.utcoffset() is None:
        raise ValueError("planned_at must include timezone information")

    profiles = pd.read_csv(config.catalog_profiles_path, dtype=str).fillna("")
    taxonomy = _load_taxonomy(config.taxonomy_path)
    parser = DemandConstraintParser.from_taxonomy(
        taxonomy,
        rules_path=config.constraint_rules_path,
        aliases_path=config.constraint_aliases_path,
    )
    scorer = E5RuntimeTextSimilarityScorer(config.e5)
    planner = ClaimIndexedSubstituteProposalPlanner(
        profiles,
        taxonomy,
        parser,
        text_similarity_scorer=scorer,
    )

    connection = connection_factory(
        config.database_url,
        config.postgres_connect_timeout_seconds,
    )
    try:
        execution = execute_demand_clustering_batch(
            PostgreSQLClusteringInputReader(connection),
            planner,
            backend_base_url=config.backend_base_url,
            internal_key=config.backend_internal_key,
            planned_at=planned_at,
            formation_rule_version=FORMATION_RULE_VERSION,
            substitute_rule_version=SUBSTITUTE_RULE_VERSION,
            min_participants=config.min_participants,
            formation_plan_poster=(
                formation_plan_poster
                or _default_formation_poster(
                    config.backend_http_timeout_seconds
                )
            ),
            substitute_plan_poster=(
                substitute_plan_poster
                or _default_substitute_poster(
                    config.backend_http_timeout_seconds
                )
            ),
            input_validator=planner.validate_input_profile_coverage,
            event_handler=event_handler,
        )
    finally:
        connection.close()

    return DemandClusteringJobResult(
        planned_at=planned_at,
        execution=execution,
        e5_cache_summary=scorer.cache_summary,
    )


def _safe_error_message(error: Exception, config: Any) -> str:
    message = str(error)
    if isinstance(config, DemandClusteringJobConfig):
        for secret in (config.database_url, config.backend_internal_key):
            if secret:
                message = message.replace(secret, "[REDACTED]")
    return message


def _write_runtime_event(
    event: str,
    fields: Mapping[str, Any],
) -> None:
    print(
        json.dumps(
            {"event": event, **fields},
            ensure_ascii=False,
            sort_keys=True,
        ),
        file=sys.stderr,
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    now: datetime | None = None,
    job_runner: Callable[..., DemandClusteringJobResult] = (
        run_demand_clustering_job
    ),
) -> int:
    parser = argparse.ArgumentParser(
        description="Run one Backend-integrated demand clustering batch."
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        help="Optional local dotenv file; existing environment values win.",
    )
    args = parser.parse_args(argv)

    if args.env_file is not None:
        if environ is not None:
            parser.error("--env-file cannot be combined with injected environ")
        if not args.env_file.is_file():
            print(
                json.dumps({
                    "status": "CONFIGURATION_ERROR",
                    "message": "--env-file must reference an existing file",
                }),
                file=sys.stderr,
            )
            return 2
        load_dotenv(args.env_file, override=False)

    config: DemandClusteringJobConfig | None = None
    try:
        config = load_job_config(environ)
        planned_at = now or datetime.now().astimezone()
        result = job_runner(
            config,
            planned_at=planned_at,
            event_handler=_write_runtime_event,
        )
    except ConfigurationError as error:
        print(
            json.dumps({
                "status": "CONFIGURATION_ERROR",
                "message": _safe_error_message(error, config),
            }, ensure_ascii=False),
            file=sys.stderr,
        )
        return 2
    except Exception as error:
        print(
            json.dumps({
                "status": "FAILED",
                "errorType": type(error).__name__,
                "message": _safe_error_message(error, config),
            }, ensure_ascii=False),
            file=sys.stderr,
        )
        return 1

    print(json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
