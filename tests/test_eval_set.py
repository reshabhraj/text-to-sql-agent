"""Integrity of eval/questions.jsonl.

The reference SQL is what every model is scored against, so each query must
pass the guardrails, run, and return rows; and none of the questions may be
one the model was already shown as a few-shot example.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import pytest

from eval.run_eval import CATEGORIES, Question, load_questions
from src.config import ConfigError
from src.executor import execute
from src.generator import EXAMPLES, build_prompt
from src.guardrails import validate
from src.providers.mock_provider import MockProvider

QUESTIONS = load_questions()


def _normalise(text: str) -> str:
    return re.sub(r"\d+", "", " ".join(text.lower().split()))


def test_twenty_five_questions_five_per_category() -> None:
    assert len(QUESTIONS) == 25
    assert len({q.id for q in QUESTIONS}) == 25
    assert Counter(q.category for q in QUESTIONS) == {c: 5 for c in CATEGORIES}


def test_only_ranking_questions_are_ordered() -> None:
    assert all(isinstance(q.ordered, bool) for q in QUESTIONS)
    assert {q.id for q in QUESTIONS if q.ordered} == {"hard_01", "hard_03"}


@pytest.mark.parametrize("question", QUESTIONS, ids=lambda q: q.id)
def test_reference_passes_guardrails_and_returns_rows(
    question: Question, settings, allowed_tables
) -> None:
    checked = validate(question.reference_sql, allowed_tables)
    assert checked.ok, checked.reason
    result = execute(checked.sql, settings)
    assert result.columns
    assert result.rows


def test_no_question_duplicates_a_few_shot_example() -> None:
    example_questions = {_normalise(q) for q, _ in EXAMPLES}
    example_sql = {_normalise(sql) for _, sql in EXAMPLES}
    for question in QUESTIONS:
        assert _normalise(question.question) not in example_questions, question.id
        assert _normalise(question.reference_sql) not in example_sql, question.id


def test_mock_answers_every_question_with_its_reference_sql() -> None:
    provider = MockProvider()
    for question in QUESTIONS:
        answer = provider.generate_sql(build_prompt(question.question, "schema"))
        assert answer == question.reference_sql, question.id


# Loader error paths


def _record(**overrides) -> dict:
    record = {
        "id": "simple_01",
        "category": "simple",
        "question": "How many?",
        "reference_sql": "SELECT 1",
        "ordered": False,
    }
    record.update(overrides)
    return record


def _write(path: Path, records: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return path


def test_duplicate_id_is_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path / "q.jsonl", [_record(), _record()])
    with pytest.raises(ConfigError) as excinfo:
        load_questions(path)
    assert "simple_01" in str(excinfo.value)


def test_unknown_category_is_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path / "q.jsonl", [_record(category="weird")])
    with pytest.raises(ConfigError) as excinfo:
        load_questions(path)
    assert "weird" in str(excinfo.value)


def test_missing_field_is_rejected(tmp_path: Path) -> None:
    record = _record()
    del record["ordered"]
    path = _write(tmp_path / "q.jsonl", [record])
    with pytest.raises(ConfigError) as excinfo:
        load_questions(path)
    assert "ordered" in str(excinfo.value)


def test_missing_file_is_a_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_questions(tmp_path / "absent.jsonl")
