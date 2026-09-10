"""Read-only PostgreSQL input adapter for the A labeling batch."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol

import pandas as pd


DEFAULT_DEMANDS_SQL = """
SELECT
    d.id AS demand_id,
    d.catalog_id,
    pc.category_id,
    d.extra_requirement,
    d.desired_price_min,
    d.desired_price_max,
    d.quantity,
    d.is_substitutable,
    d.processed_at
FROM demand AS d
JOIN product_catalog AS pc ON pc.id = d.catalog_id
WHERE d.processed_at IS NULL
ORDER BY d.id
""".strip()


class Cursor(Protocol):
    description: Sequence[Any] | None

    def __enter__(self) -> "Cursor": ...
    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None: ...
    def execute(self, query: str, params: Mapping[str, Any] | None = None) -> Any: ...
    def fetchall(self) -> Sequence[Any]: ...


class Connection(Protocol):
    def cursor(self) -> Cursor: ...


def _column_name(item: Any) -> str:
    name = getattr(item, "name", None)
    return str(name if name is not None else item[0])


def read_unprocessed_demands(
    connection: Connection,
    *,
    as_of: datetime | None = None,
    query: str = DEFAULT_DEMANDS_SQL,
) -> pd.DataFrame:
    """Read labeling inputs without performing database writes."""
    with connection.cursor() as cursor:
        cursor.execute(query, {"as_of": as_of} if as_of is not None else None)
        rows = cursor.fetchall()
        if not rows:
            return pd.DataFrame(
                columns=["demand_id", "catalog_id", "category_id", "extra_requirement"]
            )
        if all(isinstance(row, Mapping) for row in rows):
            return pd.DataFrame(rows).fillna("")
        if cursor.description is None:
            raise RuntimeError("cursor description is required for tuple rows")
        columns = [_column_name(item) for item in cursor.description]
        return pd.DataFrame([dict(zip(columns, row, strict=True)) for row in rows]).fillna("")


def open_read_only_postgres(database_url: str, connect_timeout_seconds: int = 10) -> Any:
    """Open a server-enforced read-only session; credentials stay in the environment."""
    try:
        import psycopg
    except ImportError as error:
        raise RuntimeError("A labeling runtime requires psycopg") from error
    connection = psycopg.connect(
        database_url,
        connect_timeout=connect_timeout_seconds,
        options="-c default_transaction_read_only=on",
    )
    connection.autocommit = True
    return connection
