"""End to end through Agent.ask() with the mock provider.

Covers the happy path, the self-correction loop, its cap, the refusal to run
a write statement, and the rule that a corrected query goes back through the
guardrails instead of around them.
"""

from __future__ import annotations

import pytest

from src.agent import MAX_CORRECTIONS, Agent
from src.providers.base import LLMProvider
from src.providers.mock_provider import BROKEN_SQL, MockProvider

SLOW_SQL = "SELECT count(*) FROM ad_clicks a, ad_clicks b, ad_clicks c"


class ScriptedProvider(LLMProvider):
    """Returns the given answers in order and keeps every prompt it was sent."""

    def __init__(self, answers: list[str]) -> None:
        self._answers = list(answers)
        self.prompts: list[str] = []

    @property
    def name(self) -> str:
        return "scripted"

    def generate_sql(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self._answers.pop(0)


@pytest.mark.parametrize(
    "question, expected",
    [
        ("How many customers are from Italy?", [(14,)]),
        ("How many orders have status pending?", [(82,)]),
    ],
)
def test_known_question_runs_first_time(agent: Agent, question: str, expected) -> None:
    result = agent.ask(question)
    assert result.ok
    assert result.attempts == 0
    assert result.rejected_reason is None
    assert result.error is None
    assert result.rows == expected
    assert result.provider == "mock"


def test_grouped_question(agent: Agent) -> None:
    result = agent.ask("How many orders are there per status? Return status and count.")
    assert result.ok
    assert result.attempts == 0
    assert len(result.columns) == 2
    assert set(result.rows) == {("paid", 574), ("pending", 82), ("refunded", 144)}


def test_correction_loop_recovers_from_a_bad_column(settings) -> None:
    provider = MockProvider(fail_once=True)
    result = Agent(settings, provider).ask("How many customers are from Italy?")
    assert result.ok
    assert result.attempts == 1
    assert result.rows == [(14,)]
    assert provider.calls == 2
    assert "customer_count" in result.sql
    assert "nonexistent_col" not in result.sql


def test_correction_prompt_carries_the_failed_sql_and_error(settings) -> None:
    provider = ScriptedProvider([BROKEN_SQL, "SELECT count(*) AS n FROM customers"])
    result = Agent(settings, provider).ask("How many customers are there?")
    assert result.ok
    assert result.attempts == 1
    assert len(provider.prompts) == 2
    assert BROKEN_SQL in provider.prompts[1]
    assert "nonexistent_col" in provider.prompts[1]
    assert "How many customers are there?" in provider.prompts[1]


def test_write_statement_is_refused_before_execution(settings, row_count) -> None:
    provider = MockProvider(forced_sql="DELETE FROM orders")
    result = Agent(settings, provider).ask("Delete every order")
    assert not result.ok
    assert result.rejected_reason is not None
    assert "only SELECT queries are allowed" in result.rejected_reason
    assert result.attempts == 0
    assert result.rows == []
    assert result.columns == []
    assert provider.calls == 1
    assert row_count("orders") == 800


def test_correction_cap_holds(settings) -> None:
    provider = MockProvider(forced_sql=BROKEN_SQL)
    result = Agent(settings, provider).ask("anything")
    assert not result.ok
    assert result.attempts == MAX_CORRECTIONS == 2
    assert result.error is not None
    assert "nonexistent_col" in result.error
    assert result.rejected_reason is None
    assert provider.calls == MAX_CORRECTIONS + 1


def test_timeout_is_not_sent_back_for_correction(make_settings) -> None:
    provider = MockProvider(forced_sql=SLOW_SQL)
    result = Agent(make_settings(query_timeout_seconds=1), provider).ask("anything")
    assert not result.ok
    assert result.timed_out is True
    assert result.error
    assert result.attempts == 0
    assert provider.calls == 1


def test_corrected_sql_goes_back_through_guardrails(settings, row_count) -> None:
    provider = ScriptedProvider([BROKEN_SQL, "DELETE FROM orders"])
    result = Agent(settings, provider).ask("anything")
    assert not result.ok
    assert result.attempts == 1
    assert result.rejected_reason is not None
    assert result.rows == []
    assert len(provider.prompts) == 2
    assert row_count("orders") == 800


def test_unknown_question_falls_back_to_select_1(agent: Agent) -> None:
    result = agent.ask("What colour is the sky?")
    assert result.ok
    assert result.attempts == 0
    assert result.rows == [(1,)]
