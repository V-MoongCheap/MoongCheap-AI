"""Read-only PostgreSQL input adapter for the A labeling batch."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Any, Protocol, Self

import pandas as pd

DEFAULT_DEMANDS_SQL_WITH_CATEGORY = """
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
WHERE d.status = 'UNASSIGNED'
  AND d.processed_at IS NULL
ORDER BY d.id
""".strip()

# The current Backend migration does not have product_catalog.category_id.
# Keep the base query free of that column so a supplied, authoritative
# catalog-to-category mapping can be used on that schema.
DEFAULT_DEMANDS_SQL = """
SELECT
    d.id AS demand_id,
    d.catalog_id,
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

SCHEMA_PROBE_SQL = """
SELECT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = current_schema()
      AND table_name = 'product_catalog'
      AND column_name = 'category_id'
) AS has_category_id
""".strip()

CATEGORY_FACETS_SQL = """
SELECT id AS category_db_id, facet AS category_facet
FROM category
WHERE id = ANY(%(category_ids)s)
""".strip()

CATALOG_CATEGORY_MAP_ENV = "A_CATALOG_CATEGORY_MAP_PATH"


class Cursor(Protocol):
    description: Sequence[Any] | None

    def __enter__(self) -> Self: ...
    def __exit__(self, exc_type: type[BaseException] | None, exc_value: BaseException | None, traceback: TracebackType | None) -> None: ...
    def execute(self, query: str, params: Mapping[str, Any] | None = None) -> Any: ...
    def fetchall(self) -> Sequence[Any]: ...


class Connection(Protocol):
    def cursor(self) -> Cursor: ...


def _column_name(item: Any) -> str:
    name = getattr(item, "name", None)
    return str(name if name is not None else item[0])


def _frame_from_cursor(cursor: Cursor) -> pd.DataFrame:
    rows = cursor.fetchall()
    if not rows:
        return pd.DataFrame()
    if all(isinstance(row, Mapping) for row in rows):
        return pd.DataFrame(rows).fillna("")
    if cursor.description is None:
        raise RuntimeError("cursor description is required for tuple rows")
    columns = [_column_name(item) for item in cursor.description]
    return pd.DataFrame([dict(zip(columns, row, strict=True)) for row in rows]).fillna("")


def _has_product_catalog_category_id(connection: Connection) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(SCHEMA_PROBE_SQL)
        frame = _frame_from_cursor(cursor)
    if frame.empty or "has_category_id" not in frame.columns:
        raise RuntimeError("schema probe did not return product_catalog.category_id status")
    value = frame.iloc[0]["has_category_id"]
    return value is True or str(value).strip().lower() in {"1", "true", "t", "yes"}


def _load_catalog_category_map(path: Path) -> dict[str, str]:
    try:
        mapping = pd.read_csv(path, dtype=str).fillna("")
    except (OSError, pd.errors.ParserError) as error:
        raise RuntimeError(f"failed to read catalog/category mapping: {path}") from error
    required = {"catalog_id", "category_id"}
    missing = required - set(mapping.columns)
    if missing:
        raise RuntimeError(
            f"catalog/category mapping is missing columns: {sorted(missing)}; "
            "category_id must be the actual Backend category.id"
        )
    result: dict[str, str] = {}
    for _, row in mapping.iterrows():
        catalog_id = str(row["catalog_id"]).strip()
        category_id = str(row["category_id"]).strip()
        if not catalog_id or not category_id:
            raise RuntimeError("catalog/category mapping contains an empty catalog_id or category_id")
        previous = result.get(catalog_id)
        if previous is not None and previous != category_id:
            raise RuntimeError(f"catalog_id has conflicting category IDs: {catalog_id}")
        result[catalog_id] = category_id
    if not result:
        raise RuntimeError("catalog/category mapping is empty")
    return result


def _attach_categories_from_mapping(
    connection: Connection,
    demands: pd.DataFrame,
    mapping_path: Path,
) -> pd.DataFrame:
    catalog_to_category = _load_catalog_category_map(mapping_path)
    frame = demands.copy()
    frame["category_db_id"] = frame["catalog_id"].astype(str).map(catalog_to_category).fillna("")
    missing = frame["category_db_id"].eq("")
    if missing.any():
        sample = ", ".join(frame.loc[missing, "catalog_id"].astype(str).head(5))
        raise RuntimeError(
            f"catalog/category mapping has no Backend category.id for "
            f"{int(missing.sum())} catalog rows (sample: {sample})"
        )
    category_ids = sorted(set(frame["category_db_id"].astype(str)))
    with connection.cursor() as cursor:
        cursor.execute(CATEGORY_FACETS_SQL, {"category_ids": category_ids})
        categories = _frame_from_cursor(cursor)
    if categories.empty:
        raise RuntimeError("category lookup returned no rows for the supplied Backend category IDs")
    known = dict(zip(categories["category_db_id"].astype(str), categories["category_facet"], strict=False))
    frame["category_facet"] = frame["category_db_id"].astype(str).map(known).fillna("")
    missing_facets = frame["category_facet"].eq("")
    if missing_facets.any():
        sample = ", ".join(frame.loc[missing_facets, "category_db_id"].astype(str).unique()[:5])
        raise RuntimeError(f"category.facet is missing for Backend category IDs (sample: {sample})")
    return frame


def read_unprocessed_demands(
    connection: Connection,
    *,
    as_of: datetime | None = None,
    query: str | None = None,
    category_mapping_path: Path | None = None,
) -> pd.DataFrame:
    """Read labeling inputs without performing database writes."""
    custom_query = query is not None
    query = query or DEFAULT_DEMANDS_SQL
    has_category_id = True
    if not custom_query:
        has_category_id = _has_product_catalog_category_id(connection)
    with connection.cursor() as cursor:
        if custom_query:
            cursor.execute(query, {"as_of": as_of} if as_of is not None else None)
            frame = _frame_from_cursor(cursor)
        else:
            if has_category_id:
                cursor.execute(
                    DEFAULT_DEMANDS_SQL_WITH_CATEGORY,
                    {"as_of": as_of} if as_of is not None else None,
                )
                frame = _frame_from_cursor(cursor)
            else:
                cursor.execute(
                    DEFAULT_DEMANDS_SQL,
                    {"as_of": as_of} if as_of is not None else None,
                )
                frame = _frame_from_cursor(cursor)
    if frame.empty:
        return pd.DataFrame(
            columns=["demand_id", "catalog_id", "category_id", "category_db_id", "category_facet", "extra_requirement"]
        )
    if not custom_query and not has_category_id:
        raw_path = category_mapping_path or (
            Path(os.environ[CATALOG_CATEGORY_MAP_ENV])
            if os.environ.get(CATALOG_CATEGORY_MAP_ENV, "").strip()
            else None
        )
        if raw_path is None:
            raise RuntimeError(
                "product_catalog.category_id is absent in the current Backend schema. "
                f"Provide an authoritative catalog_id/category_id CSV via {CATALOG_CATEGORY_MAP_ENV}; "
                "do not infer the relationship from product names or numeric IDs."
            )
        frame = _attach_categories_from_mapping(connection, frame, raw_path)
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
