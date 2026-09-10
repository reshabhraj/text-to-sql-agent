"""The execution-accuracy metric and the results file writer in eval/run_eval.py."""

from __future__ import annotations

from pathlib import Path

from eval.run_eval import (
    MAX_NOTE_LENGTH,
    MOCK_NOTICE,
    Outcome,
    Question,
    Summary,
    cells_match,
    clean_note,
    compare_results,
    split_sections,
    update_results_file,
)
from src.executor import QueryResult


def qr(rows: list[tuple], width: int = 1) -> QueryResult:
    return QueryResult([f"c{i}" for i in range(width)], rows, False)


# Cells


def test_equal_values_match() -> None:
    assert cells_match("paid", "paid")
    assert cells_match(5, 5)
    assert cells_match("2026-03", "2026-03")


def test_int_and_float_compare_numerically() -> None:
    assert cells_match(574, 574.0)


def test_numeric_tolerance() -> None:
    assert cells_match(1.0, 1.005)
    assert not cells_match(1.0, 1.02)


def test_noisy_float_matches_numeric_text() -> None:
    assert cells_match(608.5500000001, "608.55")
    assert cells_match("608.55", 608.5500000001)


def test_different_strings_do_not_match() -> None:
    assert not cells_match("paid", "pending")


def test_none_matches_only_none() -> None:
    assert cells_match(None, None)
    assert not cells_match(None, 0)
    assert not cells_match("", None)


# Result sets


def test_identical_results_match() -> None:
    rows = [("paid", 574), ("pending", 82)]
    assert compare_results(qr(rows, 2), qr(rows, 2), ordered=False) == (True, "")


def test_column_count_must_match() -> None:
    ok, why = compare_results(qr([(1,)], 1), qr([(1, 2)], 2), ordered=False)
    assert not ok
    assert "column count" in why


def test_row_count_must_match() -> None:
    ok, why = compare_results(qr([(1,), (2,)]), qr([(1,)]), ordered=False)
    assert not ok
    assert "row count" in why


def test_unordered_comparison_accepts_shuffled_rows() -> None:
    expected = [(1,), (2,), (3,)]
    actual = [(3,), (1,), (2,)]
    assert compare_results(qr(expected), qr(actual), ordered=False) == (True, "")


def test_ordered_comparison_rejects_shuffled_rows() -> None:
    expected = [(1,), (2,), (3,)]
    actual = [(3,), (1,), (2,)]
    ok, why = compare_results(qr(expected), qr(actual), ordered=True)
    assert not ok
    assert why == "row 1 differs"


def test_duplicate_rows_are_counted_not_collapsed() -> None:
    ok, why = compare_results(qr([(1,), (1,)]), qr([(1,), (2,)]), ordered=False)
    assert not ok
    assert "not found" in why


def test_column_names_are_ignored() -> None:
    expected = QueryResult(["paid_revenue"], [(100.0,)], False)
    actual = QueryResult(["revenue"], [(100.004,)], False)
    assert compare_results(expected, actual, ordered=False) == (True, "")


# Notes


def test_clean_note_collapses_whitespace_and_escapes_pipes() -> None:
    assert clean_note("a  b\n c | d") == "a b c \\| d"


def test_clean_note_truncates_long_text() -> None:
    note = clean_note("x" * (MAX_NOTE_LENGTH + 50))
    assert len(note) == MAX_NOTE_LENGTH
    assert note.endswith("...")


# Results file


def _summary(provider: str, correct: bool = True) -> Summary:
    question = Question("simple_01", "simple", "How many?", "SELECT 1", False)
    outcome = Outcome(question, correct, 0, False, False, "", 0.0, "SELECT 1")
    model = "none" if provider == "mock" else "some-model"
    return Summary(provider, model, "2026-09-10", [outcome], 0.1)


def test_summary_counts() -> None:
    question = Question("simple_01", "simple", "How many?", "SELECT 1", False)
    outcomes = [
        Outcome(question, True, 0, False, False, "", 0.0, "SELECT 1"),
        Outcome(question, True, 1, False, False, "", 0.0, "SELECT 1"),
        Outcome(question, False, 0, True, False, "rejected", 0.0, "DELETE"),
        Outcome(question, False, 2, False, True, "database error", 0.0, "SELECT x"),
    ]
    summary = Summary("mock", "none", "2026-09-10", outcomes, 0.1)
    assert summary.total == 4
    assert summary.correct == 2
    assert summary.accuracy == 50.0
    assert summary.corrected == 2
    assert summary.rejected == 1
    assert summary.failed == 1
    assert summary.by_category() == [("simple", 2, 4)]


def test_results_file_replaces_its_own_section(tmp_path: Path) -> None:
    path = tmp_path / "results.md"
    update_results_file(path, _summary("mock"))
    update_results_file(path, _summary("mock"))
    text = path.read_text(encoding="utf-8")
    assert split_sections(text)[0] == ["mock"]
    assert text.count("## mock") == 1
    assert MOCK_NOTICE in text


def test_results_file_keeps_other_sections(tmp_path: Path) -> None:
    path = tmp_path / "results.md"
    update_results_file(path, _summary("mock"))
    update_results_file(path, _summary("groq"))
    update_results_file(path, _summary("mock", correct=False))
    order, sections = split_sections(path.read_text(encoding="utf-8"))
    assert order == ["mock", "groq"]
    assert "0/1" in sections["mock"]
    assert "1/1" in sections["groq"]
    assert MOCK_NOTICE in sections["mock"]
    assert MOCK_NOTICE not in sections["groq"]
