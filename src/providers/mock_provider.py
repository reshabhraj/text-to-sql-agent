"""A deterministic provider that needs no network and no API key.

It exists so the tests, the CI job, and the evaluation harness can exercise
every part of the agent without depending on an external API. Its answers are
the reference SQL from eval/questions.jsonl, the same file the harness scores
against, so a mock evaluation run measures the harness, not model quality,
and eval/results.md says so.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..config import ROOT, ConfigError
from .base import LLMProvider

QUESTION_PREFIX = "Question:"

# Returned when fail_once is set, to exercise the self-correction loop.
# The table exists but the column does not, so guardrails pass it and the
# database rejects it, which is exactly the error the loop is built for.
BROKEN_SQL = "SELECT nonexistent_col FROM customers"

QUESTIONS_PATH = ROOT / "eval" / "questions.jsonl"


def load_reference_sql(path: Path = QUESTIONS_PATH) -> dict[str, str]:
    """Map every evaluation question to its reference SQL.

    Reading the evaluation file instead of keeping a second copy of the SQL
    here means the mock can never drift from what the harness compares
    against. Only the two fields the mock needs are read; the harness does
    the full validation of the file.
    """
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"Evaluation questions not found at {path}.")
    answers: dict[str, str] = {}
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                answers[record["question"]] = record["reference_sql"]
            except (ValueError, KeyError, TypeError):
                raise ConfigError(
                    f"{path} line {line_number} is not a question record "
                    "with 'question' and 'reference_sql' fields."
                ) from None
    return answers


def normalise(question: str) -> str:
    """Collapse a question to a stable lookup key."""
    return " ".join(question.strip().lower().rstrip(" .?!").split())


def extract_question(prompt: str) -> str:
    """Pull the real question out of a full generator prompt.

    The prompt carries one 'Question:' line per few-shot example and then the
    real question last, so this takes the LAST match. Taking the first would
    return few-shot example one every time and every lookup would miss.
    A prompt with no marker at all is treated as a bare question.
    """
    found = None
    for line in prompt.splitlines():
        stripped = line.strip()
        if stripped.startswith(QUESTION_PREFIX):
            found = stripped[len(QUESTION_PREFIX):].strip()
    return found if found is not None else prompt.strip()


class MockProvider(LLMProvider):
    """Looks the question up in a fixed table. Unknown questions get SELECT 1.

    The table is loaded from eval/questions.jsonl unless answers is given.
    fail_once returns broken SQL on the first call and correct SQL afterwards,
    which drives the self-correction loop. forced_sql always returns the same
    text, used to check that the agent refuses to execute a write statement.
    """

    def __init__(
        self,
        settings: object = None,
        answers: dict[str, str] | None = None,
        fail_once: bool = False,
        forced_sql: str | None = None,
    ) -> None:
        # settings is accepted and ignored so every provider shares one
        # constructor shape and the factory needs no special cases.
        del settings
        source = load_reference_sql() if answers is None else answers
        self._answers = {normalise(q): sql.strip() for q, sql in source.items()}
        self._fail_once = fail_once
        self._forced_sql = forced_sql
        self.calls = 0

    @property
    def name(self) -> str:
        return "mock"

    def generate_sql(self, prompt: str) -> str:
        self.calls += 1
        if self._forced_sql is not None:
            return self._forced_sql
        if self._fail_once and self.calls == 1:
            return BROKEN_SQL
        return self._answers.get(normalise(extract_question(prompt)), "SELECT 1")
