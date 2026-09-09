"""Read the live database schema and render it compactly for the prompt.

Introspecting at runtime instead of hand-writing a schema block means the
prompt stays correct when the database changes, and the table allowlist the
guardrails use always matches what actually exists.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .config import ConfigError, Settings


@dataclass(frozen=True)
class TableInfo:
    name: str
    columns: list[tuple[str, str]]


@dataclass(frozen=True)
class ForeignKey:
    table: str
    column: str
    ref_table: str
    ref_column: str


@dataclass(frozen=True)
class SchemaInfo:
    tables: list[TableInfo]
    foreign_keys: list[ForeignKey]

    def table_names(self) -> list[str]:
        """The guardrail allowlist: every table the model may reference."""
        return [table.name for table in self.tables]

    def render(self) -> str:
        """One line per table, then one line per foreign key."""
        lines = [
            f"{table.name}({', '.join(f'{col} {typ}' for col, typ in table.columns)})"
            for table in self.tables
        ]
        lines.extend(
            f"{fk.table}.{fk.column} -> {fk.ref_table}.{fk.ref_column}"
            for fk in self.foreign_keys
        )
        return "\n".join(lines)


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _sqlite_schema(conn: sqlite3.Connection) -> SchemaInfo:
    conn.row_factory = sqlite3.Row
    names = [
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]

    tables: list[TableInfo] = []
    primary_keys: dict[str, str] = {}
    for name in names:
        # PRAGMA does not accept bound parameters, so the identifier is
        # interpolated. Names come only from sqlite_master, never from input.
        rows = conn.execute(f"PRAGMA table_info({_quote_ident(name)})").fetchall()
        tables.append(
            TableInfo(name, [(row["name"], (row["type"] or "TEXT").upper()) for row in rows])
        )
        pk = [row["name"] for row in rows if row["pk"]]
        primary_keys[name] = pk[0] if pk else "id"

    foreign_keys: list[ForeignKey] = []
    for name in names:
        # Columns are (id, seq, table, from, to, on_update, on_delete, match),
        # read by name rather than by position.
        for row in conn.execute(f"PRAGMA foreign_key_list({_quote_ident(name)})").fetchall():
            ref_table = row["table"]
            # "to" is NULL when the schema wrote REFERENCES t instead of
            # REFERENCES t(col). Fall back to that table's primary key so the
            # prompt never shows a None.
            ref_column = row["to"] or primary_keys.get(ref_table, "id")
            foreign_keys.append(ForeignKey(name, row["from"], ref_table, ref_column))

    foreign_keys.sort(key=lambda fk: (fk.table, fk.column))
    return SchemaInfo(tables, foreign_keys)


def _postgres_schema(conn) -> SchemaInfo:
    columns_by_table: dict[str, list[tuple[str, str]]] = {}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name, column_name, data_type
              FROM information_schema.columns
             WHERE table_schema = 'public'
             ORDER BY table_name, ordinal_position
            """
        )
        for table_name, column_name, data_type in cur.fetchall():
            columns_by_table.setdefault(table_name, []).append(
                (column_name, str(data_type).upper())
            )

        cur.execute(
            """
            SELECT tc.table_name, kcu.column_name,
                   ccu.table_name AS ref_table, ccu.column_name AS ref_column
              FROM information_schema.table_constraints tc
              JOIN information_schema.key_column_usage kcu
                ON kcu.constraint_name = tc.constraint_name
               AND kcu.table_schema = tc.table_schema
              JOIN information_schema.constraint_column_usage ccu
                ON ccu.constraint_name = tc.constraint_name
               AND ccu.table_schema = tc.table_schema
             WHERE tc.constraint_type = 'FOREIGN KEY'
               AND tc.table_schema = 'public'
             ORDER BY tc.table_name, kcu.column_name
            """
        )
        foreign_keys = [ForeignKey(*row) for row in cur.fetchall()]

    tables = [TableInfo(name, cols) for name, cols in sorted(columns_by_table.items())]
    return SchemaInfo(tables, foreign_keys)


def introspect(settings: Settings) -> SchemaInfo:
    """Read the schema of the database named by settings."""
    if settings.uses_postgres:
        try:
            import psycopg
        except ImportError:
            raise ConfigError(
                "DATABASE_URL is set but psycopg is not installed. "
                "Run: pip install 'psycopg[binary]'"
            ) from None
        with psycopg.connect(settings.database_url) as conn:
            return _postgres_schema(conn)

    path = Path(settings.database_path)
    if not path.exists():
        raise ConfigError(
            f"Database not found at {path}. Create it with: python -m db.seed"
        )
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        return _sqlite_schema(conn)
    finally:
        conn.close()
