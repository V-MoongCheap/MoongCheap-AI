import sqlite3
from pathlib import Path
from typing import Self

import pandas as pd
import pytest

from moongcheap_ai.data_foundation.postgres_reader import (
    DEFAULT_DEMANDS_SQL,
    DEFAULT_DEMANDS_SQL_WITH_CATEGORY,
    read_unprocessed_demands,
    resolve_taxonomy_category_keys,
)


@pytest.mark.parametrize("query", [DEFAULT_DEMANDS_SQL, DEFAULT_DEMANDS_SQL_WITH_CATEGORY])
def test_reader_selects_only_writable_pending_demands(query: str) -> None:
    with sqlite3.connect(":memory:") as connection:
        connection.executescript("""
            CREATE TABLE demand (id INTEGER, catalog_id INTEGER, extra_requirement TEXT,
                desired_price_min INTEGER, desired_price_max INTEGER, quantity INTEGER,
                is_substitutable INTEGER, processed_at TEXT, status TEXT);
            CREATE TABLE product_catalog (id INTEGER, category_id INTEGER);
            CREATE TABLE category (id INTEGER, facet TEXT);
            INSERT INTO product_catalog VALUES (1, 1);
            INSERT INTO category VALUES (1, '{}');
        """)
        statuses = ["UNASSIGNED", "ASSIGNED", "SUBSTITUTE_OFFERED", "PAYMENT_PENDING",
                    "FAILED", "CANCELED", "CLOSED", "EXPIRED", None, "UNKNOWN"]
        connection.executemany(
            "INSERT INTO demand (id, catalog_id, status) VALUES (?, 1, ?)",
            enumerate(statuses, start=1),
        )
        connection.execute("INSERT INTO demand (id, catalog_id, status, processed_at) VALUES (99, 1, 'UNASSIGNED', '2026-09-30')")
        assert [row[0] for row in connection.execute(query)] == [1]


def test_resolve_category_key_from_full_facet_text() -> None:
    frame = pd.DataFrame([{
        "category_db_id": 8,
        "category_id": 8,
        "category_facet": '{"category_id":"health-functional-food:probiotics","facets":[]}',
    }])

    resolved = resolve_taxonomy_category_keys(frame)

    assert resolved.loc[0, "category_id"] == "health-functional-food:probiotics"


def test_resolve_category_key_keeps_db_id_when_facet_is_not_mapped() -> None:
    frame = pd.DataFrame([{
        "category_db_id": 8,
        "category_id": 8,
        "category_facet": "[]",
    }])

    resolved = resolve_taxonomy_category_keys(frame)

    assert resolved.loc[0, "category_id"] == 8


class _Cursor:
    def __init__(self, response: list[dict[str, object]]) -> None:
        self.response = response
        self.description = None
        self.executed: list[str] = []

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, query: str, _params: object = None) -> None:
        self.executed.append(query)

    def fetchall(self) -> list[dict[str, object]]:
        return self.response


class _Connection:
    def __init__(self, responses: list[list[dict[str, object]]]) -> None:
        self.responses = iter(responses)
        self.cursors: list[_Cursor] = []

    def cursor(self) -> _Cursor:
        cursor = _Cursor(next(self.responses))
        self.cursors.append(cursor)
        return cursor


def test_current_backend_schema_uses_authoritative_catalog_mapping(tmp_path: Path) -> None:
    mapping = tmp_path / "catalog_category.csv"
    pd.DataFrame([{"catalog_id": "3901", "category_id": "17"}]).to_csv(mapping, index=False)
    connection = _Connection([
        [{"has_category_id": False}],
        [{"demand_id": 1, "catalog_id": 3901, "extra_requirement": "", "processed_at": None}],
        [{"category_db_id": 17, "category_facet": '{"category_id":"health-functional-food:probiotics","facets":[]}'}],
    ])

    result = read_unprocessed_demands(connection, category_mapping_path=mapping)

    assert result.loc[0, "category_db_id"] == "17"
    assert result.loc[0, "category_id"] == "health-functional-food:probiotics"
    assert all("pc.category_id" not in query for cursor in connection.cursors for query in cursor.executed)


def test_current_backend_schema_fails_without_authoritative_mapping() -> None:
    connection = _Connection([
        [{"has_category_id": False}],
        [{"demand_id": 1, "catalog_id": 3901, "extra_requirement": "", "processed_at": None}],
    ])

    try:
        read_unprocessed_demands(connection)
    except RuntimeError as error:
        assert "A_CATALOG_CATEGORY_MAP_PATH" in str(error)
    else:
        raise AssertionError("missing catalog/category mapping must fail explicitly")
