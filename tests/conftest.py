"""Shared fixtures.

Every test runs against a freshly seeded temporary database, never against
data/sample.db, and builds Settings directly rather than through
load_settings(), so nothing in the developer's .env can reach the suite.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from db.seed import seed
from src.agent import Agent
from src.config import Settings
from src.providers.mock_provider import MockProvider
from src.schema_introspect import introspect


@pytest.fixture(scope="session")
def seeded_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("db") / "sample.db"
    seed(path)
    return path


@pytest.fixture
def make_settings(seeded_db: Path):
    def _make(**overrides) -> Settings:
        values = dict(
            provider="mock",
            groq_api_key="",
            groq_model="",
            gemini_api_key="",
            gemini_model="",
            anthropic_api_key="",
            anthropic_model="",
            database_url="",
            database_path=seeded_db,
            row_limit=500,
            query_timeout_seconds=10,
        )
        values.update(overrides)
        return Settings(**values)

    return _make


@pytest.fixture
def settings(make_settings) -> Settings:
    return make_settings()


@pytest.fixture
def allowed_tables(settings: Settings) -> list[str]:
    return introspect(settings).table_names()


@pytest.fixture
def agent(settings: Settings) -> Agent:
    return Agent(settings, MockProvider())


@pytest.fixture
def row_count(seeded_db: Path):
    """Count rows through a fresh, writable connection, to prove nothing changed."""

    def _count(table: str) -> int:
        conn = sqlite3.connect(seeded_db)
        try:
            return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        finally:
            conn.close()

    return _count
