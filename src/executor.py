"""Run validated SQL against the database, read-only and time-capped.

This is the second independent safety layer. The guardrails decide what may
run; this decides what the connection is even capable of. A bug in the first
layer should not be enough to write to the database.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from .config import ConfigError, Settings


class ExecutionError(Exception):
    """The database rejected the query. The message is useful to the model."""


class QueryTimeout(Exception):
    """The query ran past its time limit.

    Deliberately not a subclass of ExecutionError. A timeout is not a mistake
    the model can fix by rewriting: feeding it back would spend the correction
    budget regenerating a query that times out again.
    """


@dataclass(frozen=True)
class QueryResult:
    columns: list[str]
    rows: list[tuple]
    truncated: bool


def _connect_sqlite(settings: Settings) -> sqlite3.Connection:
    path = Path(settings.database_path)
    if not path.exists():
        raise ConfigError(
            f"Database not found at {path}. Create it with: python -m db.seed"
        )
    # as_uri() is what makes this work on Windows: a raw path would produce
    # file:D:\... and backslashes are not URI separators, so SQLite would fail
    # to open it. The resulting connection refuses every write.
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)


def _execute_sqlite(sql: str, settings: Settings) -> QueryResult:
    conn = _connect_sqlite(settings)
    deadline = time.monotonic() + settings.query_timeout_seconds

    def _watchdog() -> int:
        # Returning non-zero aborts the statement. Raising from here does not
        # propagate: SQLite swallows it and surfaces "interrupted" instead,
        # which is why the timeout is detected in the except block below.
        return 1 if time.monotonic() > deadline else 0

    conn.set_progress_handler(_watchdog, 1000)
    try:
        cursor = conn.execute(sql)
        columns = [column[0] for column in cursor.description or []]
        # One row more than the cap, so a full page can be told from a
        # truncated one without counting the whole result.
        rows = cursor.fetchmany(settings.row_limit + 1)
    except sqlite3.OperationalError as exc:
        if "interrupted" in str(exc).lower():
            raise QueryTimeout(
                f"Query exceeded the {settings.query_timeout_seconds} second limit."
            ) from None
        raise ExecutionError(str(exc)) from None
    except sqlite3.Error as exc:
        raise ExecutionError(str(exc)) from None
    finally:
        conn.set_progress_handler(None, 0)
        conn.close()

    truncated = len(rows) > settings.row_limit
    return QueryResult(columns, [tuple(row) for row in rows[: settings.row_limit]], truncated)


def _execute_postgres(sql: str, settings: Settings) -> QueryResult:
    try:
        import psycopg
    except ImportError:
        raise ConfigError(
            "DATABASE_URL is set but psycopg is not installed. "
            "Run: pip install 'psycopg[binary]'"
        ) from None

    conn = psycopg.connect(settings.database_url)
    try:
        # The session itself refuses writes, the same guarantee the SQLite
        # read-only URI gives.
        conn.read_only = True
        with conn.cursor() as cursor:
            cursor.execute(
                f"SET LOCAL statement_timeout = {int(settings.query_timeout_seconds * 1000)}"
            )
            cursor.execute(sql)
            columns = [column.name for column in cursor.description or []]
            rows = cursor.fetchmany(settings.row_limit + 1)
    except psycopg.errors.QueryCanceled:
        raise QueryTimeout(
            f"Query exceeded the {settings.query_timeout_seconds} second limit."
        ) from None
    except psycopg.Error as exc:
        raise ExecutionError(str(exc).strip()) from None
    finally:
        conn.close()

    truncated = len(rows) > settings.row_limit
    return QueryResult(columns, [tuple(row) for row in rows[: settings.row_limit]], truncated)


def execute(sql: str, settings: Settings) -> QueryResult:
    """Run sql read-only and return at most settings.row_limit rows."""
    if settings.uses_postgres:
        return _execute_postgres(sql, settings)
    return _execute_sqlite(sql, settings)
