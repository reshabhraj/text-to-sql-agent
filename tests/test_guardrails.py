"""Every rule in src/guardrails.py.

Assertions use substrings and endswith rather than exact regenerated SQL:
validate() returns sqlglot's rendering of the parsed tree, and CI installs a
fresh sqlglot whose formatting and parser wording can differ from the local
one. The reasons asserted on here are written by guardrails.py itself.
"""

from __future__ import annotations

import pytest

from src.guardrails import ValidationResult, validate

TABLES = ["ad_clicks", "campaigns", "customers", "order_items", "orders", "payments", "products"]

REJECTED = [
    ("DELETE FROM orders", ["only SELECT queries are allowed", "DELETE"]),
    ("UPDATE orders SET status = 'paid'", ["only SELECT queries are allowed", "UPDATE"]),
    ("DROP TABLE orders", ["only SELECT queries are allowed", "DROP"]),
    ("INSERT INTO orders (id) VALUES (1)", ["only SELECT queries are allowed", "INSERT"]),
    ("CREATE TABLE t (id INT)", ["only SELECT queries are allowed"]),
    ("ALTER TABLE orders ADD x INT", ["only SELECT queries are allowed"]),
    ("PRAGMA table_info(orders)", ["only SELECT queries are allowed"]),
    ("ATTACH DATABASE 'x.db' AS x", ["only SELECT queries are allowed"]),
    ("VACUUM", ["only SELECT queries are allowed"]),
    ("SELECT 1; DELETE FROM orders", ["only one statement is allowed", "found 2"]),
    ("SELECT * FROM orders -- c", ["SQL comments are not allowed"]),
    ("SELECT /* c */ * FROM orders", ["SQL comments are not allowed"]),
    ("SELECT * FROM nonexistent", ["unknown table 'nonexistent'"]),
    ("SELECT 1 FROM orders WHERE id IN (SELECT id FROM secret)", ["unknown table 'secret'"]),
    ("SELECT * FROM sqlite_master", ["unknown table"]),
    ("SELECT id FROM orders UNION SELECT id FROM customers", ["only SELECT queries are allowed"]),
    ("SELECT id FROM orders EXCEPT SELECT id FROM customers", ["only SELECT queries are allowed"]),
    ("WITH x AS (DELETE FROM orders) SELECT 1", ["DELETE"]),
    ("SELECT * FROM pragma_table_info('customers')", []),
    ("SELECT * FROM main.orders", ["qualified"]),
    ("", ["the query is empty"]),
    ("   ", ["the query is empty"]),
    ("SELECT * FROM (", ["could not parse the SQL"]),
]


@pytest.mark.parametrize("sql, fragments", REJECTED, ids=[repr(sql) for sql, _ in REJECTED])
def test_rejects(sql: str, fragments: list[str]) -> None:
    result = validate(sql, TABLES)
    assert isinstance(result, ValidationResult)
    assert result.ok is False
    assert result.reason
    for fragment in fragments:
        assert fragment in result.reason


def test_rejected_sql_is_returned_unchanged() -> None:
    assert validate("DELETE FROM orders", TABLES).sql == "DELETE FROM orders"


def test_parse_failure_is_reported_as_such() -> None:
    result = validate("SELECT * FROM (", TABLES)
    assert result.reason is not None
    assert result.reason.startswith("could not parse the SQL")


def test_accepts_plain_select_and_appends_limit() -> None:
    result = validate("SELECT id FROM orders", TABLES)
    assert result.ok is True
    assert result.reason is None
    assert result.sql.endswith("LIMIT 500")
    assert result.sql.count("LIMIT") == 1


def test_custom_row_limit_is_used() -> None:
    result = validate("SELECT id FROM orders", TABLES, row_limit=25)
    assert result.ok
    assert result.sql.endswith("LIMIT 25")


def test_accepts_with_select_and_appends_limit() -> None:
    result = validate("WITH t AS (SELECT id FROM orders) SELECT * FROM t", TABLES)
    assert result.ok
    assert result.sql.startswith("WITH")
    assert result.sql.endswith("LIMIT 500")


def test_cte_name_is_not_checked_against_the_allowlist() -> None:
    assert validate("WITH x AS (SELECT 1 AS n) SELECT n FROM x", TABLES).ok


def test_double_dash_inside_a_string_is_not_a_comment() -> None:
    sql = "SELECT count(*) FROM ad_clicks WHERE landing_page = '/sale--summer'"
    result = validate(sql, TABLES)
    assert result.ok
    assert "/sale--summer" in result.sql


def test_table_names_are_case_insensitive() -> None:
    assert validate("select ID from ORDERS", TABLES).ok


def test_accepts_explicit_join() -> None:
    sql = "SELECT o.id FROM orders o JOIN customers c ON c.id = o.customer_id"
    assert validate(sql, TABLES).ok


def test_existing_limit_is_left_alone() -> None:
    result = validate("SELECT * FROM orders LIMIT 10", TABLES)
    assert result.ok
    assert result.sql == "SELECT * FROM orders LIMIT 10"


def test_large_existing_limit_is_not_lowered() -> None:
    result = validate("SELECT id FROM orders LIMIT 100000", TABLES)
    assert result.ok
    assert result.sql.endswith("LIMIT 100000")
    assert "LIMIT 500" not in result.sql
