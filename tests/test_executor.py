"""The read-only executor is the second safety layer.

Even SQL that somehow passed validation cannot write, every result is row
capped, and a runaway query is cut off by the timeout.
"""

from __future__ import annotations

import time

import pytest

from src.config import ConfigError
from src.executor import ExecutionError, QueryTimeout, execute

# 3000 rows cubed never finishes, so this is the timeout probe.
SLOW_SQL = "SELECT count(*) FROM ad_clicks a, ad_clicks b, ad_clicks c"

WRITES = [
    "INSERT INTO customers (id, name, email, country, created_at) "
    "VALUES (9999, 'x', 'x@example.com', 'Italy', '2026-01-01 00:00:00')",
    "UPDATE orders SET status = 'paid'",
    "DELETE FROM orders",
]


def test_select_returns_columns_and_rows(settings) -> None:
    result = execute("SELECT id, status FROM orders LIMIT 3", settings)
    assert result.columns == ["id", "status"]
    assert len(result.rows) == 3
    assert all(isinstance(row, tuple) for row in result.rows)
    assert result.truncated is False


@pytest.mark.parametrize("sql", WRITES, ids=["insert", "update", "delete"])
def test_writes_are_refused_by_the_connection(sql: str, settings, row_count) -> None:
    with pytest.raises(ExecutionError) as excinfo:
        execute(sql, settings)
    assert "readonly" in str(excinfo.value)
    assert row_count("orders") == 800
    assert row_count("customers") == 200


def test_row_cap_truncates_a_large_result(make_settings) -> None:
    result = execute("SELECT * FROM ad_clicks", make_settings(row_limit=10))
    assert len(result.rows) == 10
    assert result.truncated is True


def test_small_result_is_not_truncated(make_settings) -> None:
    result = execute(
        "SELECT * FROM campaigns WHERE platform = 'meta'", make_settings(row_limit=10)
    )
    assert len(result.rows) == 4
    assert result.truncated is False


def test_result_exactly_at_the_cap_is_not_truncated(make_settings) -> None:
    result = execute("SELECT * FROM ad_clicks", make_settings(row_limit=3000))
    assert len(result.rows) == 3000
    assert result.truncated is False


def test_slow_query_times_out(make_settings) -> None:
    started = time.monotonic()
    with pytest.raises(QueryTimeout):
        execute(SLOW_SQL, make_settings(query_timeout_seconds=1))
    assert time.monotonic() - started < 5.0


def test_timeout_is_not_an_execution_error() -> None:
    assert not issubclass(QueryTimeout, ExecutionError)


def test_bad_column_error_names_the_column(settings) -> None:
    with pytest.raises(ExecutionError) as excinfo:
        execute("SELECT nonexistent_col FROM customers", settings)
    assert "nonexistent_col" in str(excinfo.value)


def test_missing_database_is_a_config_error(make_settings, tmp_path) -> None:
    with pytest.raises(ConfigError) as excinfo:
        execute("SELECT 1", make_settings(database_path=tmp_path / "missing.db"))
    assert "python -m db.seed" in str(excinfo.value)
