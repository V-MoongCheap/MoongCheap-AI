import json
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from moongcheap_ai.demand_clustering import (
    PostgreSQLClusteringInputReader,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "erd_v2_input.json"


class FakeCursor:
    def __init__(
        self,
        datasets: list[tuple[tuple[str, ...], list[tuple[Any, ...]]]],
    ) -> None:
        self._datasets = datasets
        self._current_index = -1
        self.description: list[tuple[str]] | None = None
        self.executions: list[tuple[str, dict[str, Any]]] = []

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        return None

    def execute(self, query: str, params: dict[str, Any]) -> None:
        self.executions.append((query, params))
        self._current_index += 1
        columns, _ = self._datasets[self._current_index]
        self.description = [(column,) for column in columns]

    def fetchall(self) -> list[tuple[Any, ...]]:
        _, rows = self._datasets[self._current_index]
        return rows


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor
        self.cursor_calls = 0

    def cursor(self) -> FakeCursor:
        self.cursor_calls += 1
        return self._cursor


class PostgreSQLClusteringInputReaderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        cls.demand_row = fixture["demands"][0]
        cls.board_row = fixture["demand_boards"][0]
        cls.as_of = datetime.fromisoformat("2026-08-28T12:00:00+09:00")

    def make_reader(
        self,
    ) -> tuple[PostgreSQLClusteringInputReader, FakeConnection, FakeCursor]:
        demand_columns = tuple(self.demand_row)
        board_columns = tuple(self.board_row)
        cursor = FakeCursor(
            [
                (
                    demand_columns,
                    [tuple(self.demand_row[column] for column in demand_columns)],
                ),
                (
                    board_columns,
                    [tuple(self.board_row[column] for column in board_columns)],
                ),
            ]
        )
        connection = FakeConnection(cursor)
        return PostgreSQLClusteringInputReader(connection), connection, cursor

    def test_reads_typed_demand_and_board_inputs(self) -> None:
        reader, connection, _ = self.make_reader()

        batch = reader.read(as_of=self.as_of)

        self.assertEqual(connection.cursor_calls, 1)
        self.assertEqual([demand.id for demand in batch.demands], [1001])
        self.assertEqual([board.id for board in batch.boards], [3001])
        self.assertEqual(
            batch.demands[0].created_at.utcoffset(),
            timedelta(hours=9),
        )
        self.assertEqual(
            batch.boards[0].sale_end_at.utcoffset(),
            timedelta(hours=9),
        )

    def test_uses_flyway_aligned_read_filters_without_locks(self) -> None:
        reader, _, cursor = self.make_reader()

        reader.read(as_of=self.as_of)

        self.assertEqual(len(cursor.executions), 2)
        demand_sql, demand_params = cursor.executions[0]
        board_sql, board_params = cursor.executions[1]
        self.assertIn('"pay_method_id" IS NOT NULL', demand_sql)
        self.assertIn('"demand_board_id" IS NULL', demand_sql)
        self.assertIn('"processed_at" IS NOT NULL', demand_sql)
        self.assertIn("INTERVAL '2 days'", demand_sql)
        self.assertNotIn("FOR UPDATE", demand_sql)
        self.assertIn('"sale_end_at" > %(as_of)s', board_sql)
        self.assertNotIn("FOR UPDATE", board_sql)
        self.assertEqual(
            demand_params,
            {"status": "UNASSIGNED", "as_of": self.as_of},
        )
        self.assertEqual(
            board_params,
            {"status": "GB_GATHERING", "as_of": self.as_of},
        )

    def test_rejects_as_of_without_timezone_before_querying(self) -> None:
        reader, connection, cursor = self.make_reader()

        with self.assertRaisesRegex(ValueError, "timezone"):
            reader.read(as_of=datetime.fromisoformat("2026-08-28T12:00:00"))

        self.assertEqual(connection.cursor_calls, 0)
        self.assertEqual(cursor.executions, [])


if __name__ == "__main__":
    unittest.main()
