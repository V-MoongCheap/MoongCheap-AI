"""Read-only PostgreSQL adapter for demand-clustering inputs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from .input_models import DemandBoardInput, DemandInput

CLUSTERING_DEMANDS_SQL = """
SELECT
    d."id",
    d."demand_board_id",
    d."catalog_id",
    pc."name" AS "catalog_name",
    d."desired_price_min",
    d."desired_price_max",
    d."quantity",
    d."extra_requirement",
    d."is_substitutable",
    d."status",
    d."label",
    d."desire_end_at",
    d."processed_at",
    d."created_at",
    d."updated_at"
FROM "demand" AS d
JOIN "product_catalog" AS pc ON pc."id" = d."catalog_id"
WHERE d."status" = %(status)s
  AND d."demand_board_id" IS NULL
  AND d."pay_method_id" IS NOT NULL
  AND d."created_at" > %(as_of)s - INTERVAL '2 days'
  AND d."desire_end_at" > %(as_of)s
ORDER BY d."catalog_id", d."id"
""".strip()


CLUSTERING_BOARDS_SQL = """
SELECT
    db."id",
    db."catalog_id",
    pc."name" AS "catalog_name",
    db."participant_count",
    db."price_min",
    db."price_max",
    db."status",
    db."sale_end_at",
    db."created_at"
FROM "demand_board" AS db
JOIN "product_catalog" AS pc ON pc."id" = db."catalog_id"
WHERE db."status" = %(status)s
  AND db."sale_end_at" > %(as_of)s
ORDER BY db."catalog_id", db."created_at", db."id"
""".strip()


CLUSTERING_REJECTIONS_SQL = """
SELECT DISTINCT "demand_id", "demand_board_id"
FROM "reject_history"
WHERE "demand_id" = ANY(%(demand_ids)s)
  AND "demand_board_id" = ANY(%(board_ids)s)
""".strip()


class _Cursor(Protocol):
    description: Sequence[Any] | None

    def __enter__(self) -> _Cursor: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: Any,
    ) -> None: ...

    def execute(self, query: str, params: Mapping[str, Any]) -> Any: ...

    def fetchall(self) -> Sequence[Any]: ...


class PostgreSQLConnection(Protocol):
    """Small DB-API surface required from an injected PostgreSQL connection."""

    def cursor(self) -> _Cursor: ...


@dataclass(frozen=True, slots=True)
class ClusteringInputBatch:
    demands: tuple[DemandInput, ...]
    boards: tuple[DemandBoardInput, ...]
    rejected_demand_board_pairs: frozenset[tuple[int, int]] = frozenset()


def _column_name(description_item: Any) -> str:
    name = getattr(description_item, "name", None)
    if name is not None:
        return str(name)
    return str(description_item[0])


def _fetch_mappings(cursor: _Cursor) -> tuple[Mapping[str, Any], ...]:
    rows = tuple(cursor.fetchall())
    if not rows:
        return ()
    if all(isinstance(row, Mapping) for row in rows):
        return rows
    if cursor.description is None:
        raise RuntimeError("cursor description is required for tuple rows")

    column_names = tuple(_column_name(item) for item in cursor.description)
    return tuple(
        dict(zip(column_names, row, strict=True))
        for row in rows
    )


class PostgreSQLClusteringInputReader:
    """Load eligible demands, active boards and rejection pairs without DML."""

    def __init__(self, connection: PostgreSQLConnection) -> None:
        self._connection = connection

    def read(self, *, as_of: datetime) -> ClusteringInputBatch:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must include timezone information")

        with self._connection.cursor() as cursor:
            cursor.execute(
                CLUSTERING_DEMANDS_SQL,
                {"status": "UNASSIGNED", "as_of": as_of},
            )
            demand_rows = _fetch_mappings(cursor)

            cursor.execute(
                CLUSTERING_BOARDS_SQL,
                {"status": "GB_GATHERING", "as_of": as_of},
            )
            board_rows = _fetch_mappings(cursor)

            rejection_rows: tuple[Mapping[str, Any], ...] = ()
            if demand_rows and board_rows:
                # Read all currently visible rejections, including those created
                # after as_of during API 1. A missing table or read permission
                # must fail the batch rather than silently allow repeat offers.
                cursor.execute(
                    CLUSTERING_REJECTIONS_SQL,
                    {
                        "demand_ids": [row["id"] for row in demand_rows],
                        "board_ids": [row["id"] for row in board_rows],
                    },
                )
                rejection_rows = _fetch_mappings(cursor)

        return ClusteringInputBatch(
            demands=tuple(DemandInput.from_mapping(row) for row in demand_rows),
            boards=tuple(
                DemandBoardInput.from_mapping(row) for row in board_rows
            ),
            rejected_demand_board_pairs=frozenset(
                (row["demand_id"], row["demand_board_id"])
                for row in rejection_rows
            ),
        )
