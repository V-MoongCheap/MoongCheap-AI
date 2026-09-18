from __future__ import annotations

from typing import Any

import pytest

from moongcheap_ai.data_foundation.postgres_writer import UPDATE_LABEL_SQL, write_label_results


class FakeCursor:
    def __init__(self, connection: "FakeConnection") -> None:
        self.connection = connection
        self.rowcount = 0

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        return None

    def execute(self, query: str, params: dict[str, Any] | None = None) -> None:
        if self.connection.fail:
            raise RuntimeError("write failed")
        self.connection.executed.append((query, params))
        self.rowcount = self.connection.rowcount


class FakeConnection:
    def __init__(self, *, fail: bool = False, rowcount: int = 1) -> None:
        self.fail = fail
        self.rowcount = rowcount
        self.executed: list[tuple[str, dict[str, Any] | None]] = []
        self.committed = False
        self.rolled_back = False

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True


def test_writer_updates_only_completed_rows_and_commits() -> None:
    connection = FakeConnection()
    count = write_label_results(
        connection,
        [
            {"demand_id": "1", "label": "1-2", "label_status": "LABELED"},
            {"demand_id": "2", "label": "", "label_status": "REVIEW"},
        ],
        processed_at="2026-09-14T00:00:00+00:00",
    )

    assert count == 1
    assert connection.committed is True
    assert connection.rolled_back is False
    assert len(connection.executed) == 1
    query, params = connection.executed[0]
    assert query == UPDATE_LABEL_SQL
    assert params == {"demand_id": "1", "label": "1-2", "processed_at": "2026-09-14T00:00:00+00:00"}
    assert "status = 'UNASSIGNED'" in query
    assert "processed_at IS NULL" in query


def test_writer_rolls_back_when_a_write_fails() -> None:
    connection = FakeConnection(fail=True)

    with pytest.raises(RuntimeError, match="write failed"):
        write_label_results(
            connection,
            [{"demand_id": "1", "label": "1", "label_status": "LABELED"}],
            processed_at="2026-09-14T00:00:00+00:00",
        )

    assert connection.committed is False
    assert connection.rolled_back is True


def test_writer_requires_demand_id() -> None:
    with pytest.raises(ValueError, match="demand_id"):
        write_label_results(
            FakeConnection(),
            [{"label": "1", "label_status": "LABELED"}],
            processed_at="2026-09-14T00:00:00+00:00",
        )


def test_writer_returns_database_affected_count() -> None:
    count = write_label_results(
        FakeConnection(rowcount=0),
        [{"demand_id": "already-processed", "label": "1", "label_status": "LABELED"}],
        processed_at="2026-09-14T00:00:00+00:00",
    )

    assert count == 0
