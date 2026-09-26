"""Minimal transactional writer for A labeling results.

The Backend owns the schema, while Part A owns this narrow update operation.
Only ``demand.label`` and ``demand.processed_at`` are written here.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
import math
from types import TracebackType
from typing import Any, Protocol, Self

UPDATE_LABEL_SQL = """
UPDATE demand
SET label = %(label)s,
    processed_at = %(processed_at)s,
    updated_at = NOW()
WHERE id = %(demand_id)s
  AND status = 'UNASSIGNED'
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

    The ``status = 'UNASSIGNED'`` and ``processed_at IS NULL`` guards make
    retries safe: a row already processed or assigned by another batch is not
    overwritten accidentally.
    ``REVIEW`` rows are intentionally not persisted as completed labels.
    """
    timestamp = processed_at.isoformat() if isinstance(processed_at, datetime) else str(processed_at).strip()
    if not timestamp:
        raise ValueError("processed_at is required for direct DB labeling")
    updates = []
    seen_ids: set[str] = set()
    for row in rows:
        status = str(row.get("label_status", "")).strip().upper()
        if status == "REVIEW":
            continue
        # A warning-bearing result is diagnostic only.  It must not mark the
        # demand as processed because the next batch must be able to retry it
        # after the taxonomy/model policy is improved.
        if status != "LABELED":
            raise ValueError(f"unsupported label_status for DB write: {status or '<blank>'}")
        demand_id = row.get("demand_id")
        if demand_id is None or (isinstance(demand_id, float) and math.isnan(demand_id)) or str(demand_id).strip().casefold() in {"", "nan", "none"}:
            raise ValueError("demand_id is required for direct DB labeling")
        demand_key = str(demand_id).strip()
        if demand_key in seen_ids:
            raise ValueError(f"duplicate demand_id in DB labeling batch: {demand_key}")
        seen_ids.add(demand_key)
        label = str(row.get("label", "")).strip()
        if not label:
            raise ValueError(f"label is required for demand_id: {demand_key}")
        updates.append({
            "demand_id": demand_key,
            "label": label,
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
