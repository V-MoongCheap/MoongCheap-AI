"""Minimal transactional writer for A labeling results.

The Backend owns the schema, while Part A owns this narrow update operation.
Only ``demand.label`` and ``demand.processed_at`` are written here.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from types import TracebackType
from typing import Any, Protocol, Self

UPDATE_LABEL_SQL = """
UPDATE demand
SET label = %(label)s,
    processed_at = %(processed_at)s,
    updated_at = NOW()
WHERE id = %(demand_id)s
  AND processed_at IS NULL
""".strip()


class Cursor(Protocol):
    def __enter__(self) -> Self: ...
    def __exit__(self, exc_type: type[BaseException] | None, exc_value: BaseException | None, traceback: TracebackType | None) -> None: ...
    def execute(self, query: str, params: Mapping[str, Any] | None = None) -> Any: ...


class Connection(Protocol):
    def cursor(self) -> Cursor: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...


def write_label_results(
    connection: Connection,
    rows: Iterable[Mapping[str, Any]],
    *,
    processed_at: datetime | str,
) -> int:
    """Write non-review labeling rows atomically and return updated row count.

    The ``processed_at IS NULL`` guard makes retries safe: a row already
    processed by a previous run is not overwritten accidentally.
    ``REVIEW`` rows are intentionally not persisted as completed labels.
    """
    timestamp = processed_at.isoformat() if isinstance(processed_at, datetime) else str(processed_at)
    updates = []
    for row in rows:
        if str(row.get("label_status", "")).strip().upper() == "REVIEW":
            continue
        demand_id = row.get("demand_id")
        if demand_id in (None, ""):
            raise ValueError("demand_id is required for direct DB labeling")
        updates.append({
            "demand_id": demand_id,
            "label": str(row.get("label", "")),
            "processed_at": timestamp,
        })

    updated_count = 0
    try:
        with connection.cursor() as cursor:
            for params in updates:
                cursor.execute(UPDATE_LABEL_SQL, params)
                # psycopg exposes the number of rows affected by the guarded
                # UPDATE. Keep a fallback for lightweight test doubles that
                # do not implement rowcount.
                affected = getattr(cursor, "rowcount", None)
                updated_count += affected if isinstance(affected, int) and affected >= 0 else 1
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return updated_count


def open_postgres(database_url: str, connect_timeout_seconds: int = 10) -> Any:
    """Open a writable transaction-capable PostgreSQL session.

    Credentials remain in the environment. The caller owns closing the
    connection and must invoke this only for the explicit write mode.
    """
    try:
        import psycopg
    except ImportError as error:
        raise RuntimeError("A labeling runtime requires psycopg") from error
    return psycopg.connect(database_url, connect_timeout=connect_timeout_seconds)
