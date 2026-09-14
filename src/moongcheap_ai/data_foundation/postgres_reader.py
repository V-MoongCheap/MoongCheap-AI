"""Read-only PostgreSQL input adapter for the A labeling batch."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol

import pandas as pd


DEFAULT_DEMANDS_SQL = """
SELECT
    d.id AS demand_id,
    d.catalog_id,
    pc.category_id AS category_db_id,
    c.facet AS category_facet,
    d.extra_requirement,
    d.desired_price_min,
    d.desired_price_max,
    d.quantity,
    d.is_substitutable,
    d.processed_at
FROM demand AS d
JOIN product_catalog AS pc ON pc.id = d.catalog_id
JOIN category AS c ON c.id = pc.category_id
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
                columns=["demand_id", "catalog_id", "category_id", "category_db_id", "category_facet", "extra_requirement"]
            )
        if all(isinstance(row, Mapping) for row in rows):
            return resolve_taxonomy_category_keys(pd.DataFrame(rows).fillna(""))
        if cursor.description is None:
            raise RuntimeError("cursor description is required for tuple rows")
        columns = [_column_name(item) for item in cursor.description]
        frame = pd.DataFrame([dict(zip(columns, row, strict=True)) for row in rows]).fillna("")
        return resolve_taxonomy_category_keys(frame)


def resolve_taxonomy_category_keys(demands: pd.DataFrame) -> pd.DataFrame:
    """Resolve DB category IDs to the stable key stored in facet JSON.

    Backend IDs are generated database IDs, while A taxonomy artifacts use a
    stable category key. The full ``category.facet`` text is read once and
    parsed in Python; no JSON field predicate is used in SQL.
    """
    frame = demands.copy()
    if "category_facet" not in frame.columns:
        return frame

    def key_from_facet(value: object, fallback: object) -> object:
        try:
            parsed = json.loads(str(value))
        except (TypeError, ValueError):
            return fallback
        if isinstance(parsed, dict) and parsed.get("category_id"):
            return str(parsed["category_id"])
        return fallback

    fallback_values = frame["category_db_id"] if "category_db_id" in frame.columns else frame["category_id"]
    frame["category_id"] = [
        key_from_facet(facet, fallback)
        for facet, fallback in zip(frame["category_facet"], fallback_values, strict=True)
    ]
    return frame


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
