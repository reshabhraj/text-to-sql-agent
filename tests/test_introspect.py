"""The schema block must list every table and every foreign key, because it
is both the model's only view of the database and the guardrail allowlist."""

from __future__ import annotations

import pytest

from src.schema_introspect import SchemaInfo, introspect

EXPECTED_TABLES = [
    "ad_clicks",
    "campaigns",
    "customers",
    "order_items",
    "orders",
    "payments",
    "products",
]

EXPECTED_FOREIGN_KEYS = [
    "ad_clicks.campaign_id -> campaigns.id",
    "orders.customer_id -> customers.id",
    "order_items.order_id -> orders.id",
    "order_items.product_id -> products.id",
    "payments.order_id -> orders.id",
]


@pytest.fixture
def schema(settings) -> SchemaInfo:
    return introspect(settings)


def test_lists_every_table(schema: SchemaInfo) -> None:
    assert sorted(schema.table_names()) == EXPECTED_TABLES


def test_one_line_per_table_and_per_foreign_key(schema: SchemaInfo) -> None:
    lines = schema.render().splitlines()
    assert len(lines) == len(EXPECTED_TABLES) + len(EXPECTED_FOREIGN_KEYS)
    table_lines = [line for line in lines if "->" not in line]
    assert sorted(line.split("(")[0] for line in table_lines) == EXPECTED_TABLES


def test_columns_carry_their_types(schema: SchemaInfo) -> None:
    lines = schema.render().splitlines()
    orders = next(line for line in lines if line.startswith("orders("))
    assert "session_id TEXT" in orders
    assert "total_amount NUMERIC(10, 2)" in orders
    products = next(line for line in lines if line.startswith("products("))
    assert "unit_price NUMERIC(10, 2)" in products


def test_every_foreign_key_is_listed(schema: SchemaInfo) -> None:
    fk_lines = [line for line in schema.render().splitlines() if "->" in line]
    assert sorted(fk_lines) == sorted(EXPECTED_FOREIGN_KEYS)


def test_foreign_keys_point_at_listed_tables(schema: SchemaInfo) -> None:
    names = set(schema.table_names())
    for fk in schema.foreign_keys:
        assert fk.table in names
        assert fk.ref_table in names


def test_block_never_shows_none(schema: SchemaInfo) -> None:
    assert "None" not in schema.render()
