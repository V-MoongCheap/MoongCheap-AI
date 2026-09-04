"""Read-only PostgreSQL adapter for demand-clustering inputs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from .input_models import DemandBoardInput, DemandInput


CLUSTERING_DEMANDS_SQL = """
SELECT
    "id",
    "demand_board_id",
    "catalog_id",
    "desired_price_min",
    "desired_price_max",
    "quantity",
    "is_substitutable",
    "status",
    "label",
    "desire_end_at",
    "processed_at",
    "created_at",
    "updated_at"
FROM "demand"
WHERE "status" = %(status)s
  AND "demand_board_id" IS NULL
  AND "pay_method_id" IS NOT NULL
  AND "label" IS NOT NULL
  AND btrim("label") <> ''
  AND "processed_at" IS NOT NULL
  AND "created_at" > %(as_of)s - INTERVAL '2 days'
  AND "desire_end_at" > %(as_of)s
ORDER BY "catalog_id", "id"
""".strip()


CLUSTERING_BOARDS_SQL = """
SELECT
    "id",
    "catalog_id",
    "participant_count",
    "price_min",
    "price_max",
    "status",
    "sale_end_at",
    "created_at"
FROM "demand_board"
WHERE "status" = %(status)s
  AND "sale_end_at" > %(as_of)s
ORDER BY "catalog_id", "created_at", "id"
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
    """Load eligible Demand and active DemandBoard rows without mutating DB."""

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

        return ClusteringInputBatch(
            demands=tuple(DemandInput.from_mapping(row) for row in demand_rows),
            boards=tuple(
                DemandBoardInput.from_mapping(row) for row in board_rows
            ),
        )
