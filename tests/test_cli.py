"""The command line: table formatting, result rendering, and the entry point.

main() is exercised with load_dotenv stubbed out, so the developer's .env can
never change what these tests see.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src import cli
from src.agent import AgentResult
from src.cli import MAX_DISPLAY_ROWS, format_table, render


def _result(**overrides) -> AgentResult:
    return AgentResult(question="q", provider="mock", **overrides)


# format_table


def test_format_table_aligns_columns() -> None:
    lines = format_table(["id", "name"], [(1, "Al"), (22, "Bo")]).splitlines()
    assert len(lines) == 4
    assert lines[0].split() == ["id", "name"]
    assert set(lines[1]) == {"-", " "}
    assert lines[2].split() == ["1", "Al"]
    assert lines[3].split() == ["22", "Bo"]
    assert lines[2].index("Al") == lines[3].index("Bo")


def test_format_table_with_no_rows() -> None:
    assert format_table(["a"], []) == "(no rows)"


def test_format_table_with_no_columns() -> None:
    assert format_table([], []) == "(no columns)"


def test_format_table_caps_the_display() -> None:
    rows = [(i,) for i in range(MAX_DISPLAY_ROWS + 5)]
    text = format_table(["n"], rows)
    assert "5 more rows not shown" in text
    assert text.count("\n") == MAX_DISPLAY_ROWS + 2


def test_format_table_renders_floats_and_nulls() -> None:
    text = format_table(["x", "y"], [(608.5500000001, None)])
    assert "608.55" in text
    assert "NULL" in text


# render


def test_render_rejected_result() -> None:
    text = render(_result(sql="DELETE FROM orders", rejected_reason="only SELECT queries are allowed"))
    assert "SQL used:" in text
    assert "Refused to run this query" in text
    assert "only SELECT queries are allowed" in text


def test_render_timed_out_result() -> None:
    text = render(_result(sql="SELECT 1", error="Query exceeded the 1 second limit.", timed_out=True))
    assert "Timed out" in text


def test_render_failed_result() -> None:
    text = render(_result(sql="SELECT x", error="no such column: x"))
    assert "Query failed" in text
    assert "no such column: x" in text


def test_render_successful_result_footer() -> None:
    text = render(_result(sql="SELECT 1", columns=["1"], rows=[(1,)]))
    assert "1 row, 0 corrections, provider: mock" in text


def test_render_marks_capped_results() -> None:
    text = render(_result(sql="SELECT 1", columns=["1"], rows=[(1,), (2,)], attempts=1, truncated=True))
    assert "2 rows (capped), 1 correction, provider: mock" in text


# main


@pytest.fixture
def isolated_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    monkeypatch.setattr("src.config.load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    return monkeypatch


def test_main_answers_a_question(seeded_db: Path, isolated_env, capsys) -> None:
    isolated_env.setenv("DATABASE_PATH", str(seeded_db))
    code = cli.main(["How many customers are from Italy?", "--provider", "mock"])
    out = capsys.readouterr().out
    assert code == 0
    assert "SQL used:" in out
    assert "14" in out
    assert "provider: mock" in out


def test_main_reports_a_missing_database(tmp_path: Path, isolated_env, capsys) -> None:
    isolated_env.setenv("DATABASE_PATH", str(tmp_path / "missing.db"))
    code = cli.main(["anything", "--provider", "mock"])
    assert code == 1
    assert "python -m db.seed" in capsys.readouterr().err


def test_main_rejects_an_unknown_provider() -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["anything", "--provider", "nope"])
    assert excinfo.value.code == 2
