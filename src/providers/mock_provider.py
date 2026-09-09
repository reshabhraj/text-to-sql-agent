"""A deterministic provider that needs no network and no API key.

It exists so the tests, the CI job, and the evaluation harness can exercise
every part of the agent without depending on an external API. Because it
returns known-good SQL, a mock evaluation run measures the harness, not model
quality, and eval/results.md says so.
"""

from __future__ import annotations

from .base import LLMProvider

QUESTION_PREFIX = "Question:"

# Returned when fail_once is set, to exercise the self-correction loop.
# The table exists but the column does not, so guardrails pass it and the
# database rejects it, which is exactly the error the loop is built for.
BROKEN_SQL = "SELECT nonexistent_col FROM customers"

# Reference SQL for the example questions in the build brief. Stage 6 extends
# this to the full 25-question evaluation set.
REFERENCE_SQL = {
    "How many customers are from Italy?": """
        SELECT count(*) AS customer_count
          FROM customers
         WHERE country = 'Italy'
    """,
    "List all products in the shoes category.": """
        SELECT id, name, category, unit_price
          FROM products
         WHERE category = 'shoes'
         ORDER BY name
    """,
    "Which customers placed orders in March 2026?": """
        SELECT DISTINCT c.id, c.name
          FROM customers c
          JOIN orders o ON o.customer_id = c.id
         WHERE strftime('%Y-%m', o.order_date) = '2026-03'
         ORDER BY c.name
    """,
    "What is the total paid revenue per campaign platform?": """
        SELECT k.platform, sum(o.total_amount) AS total_revenue
          FROM orders o
          JOIN ad_clicks c ON o.session_id = c.session_id
          JOIN campaigns k ON k.id = c.campaign_id
         WHERE o.status = 'paid'
         GROUP BY k.platform
         ORDER BY total_revenue DESC
    """,
    "What is the average order value for paid orders?": """
        SELECT avg(total_amount) AS average_order_value
          FROM orders
         WHERE status = 'paid'
    """,
    "How many orders were placed each month in 2026?": """
        SELECT strftime('%Y-%m', order_date) AS month, count(*) AS order_count
          FROM orders
         WHERE strftime('%Y', order_date) = '2026'
         GROUP BY month
         ORDER BY month
    """,
    "Which campaign drove the most paid revenue, attributing an order to the "
    "campaign whose ad click shares its session_id?": """
        SELECT k.name AS campaign_name, sum(o.total_amount) AS paid_revenue
          FROM orders o
          JOIN ad_clicks c ON o.session_id = c.session_id
          JOIN campaigns k ON k.id = c.campaign_id
         WHERE o.status = 'paid'
         GROUP BY k.name
         ORDER BY paid_revenue DESC
         LIMIT 1
    """,
    "What is the refund rate per product category?": """
        SELECT p.category,
               count(DISTINCT CASE WHEN o.status = 'refunded' THEN o.id END) * 1.0
                 / count(DISTINCT o.id) AS refund_rate
          FROM order_items i
          JOIN orders o ON o.id = i.order_id
          JOIN products p ON p.id = i.product_id
         GROUP BY p.category
         ORDER BY refund_rate DESC
    """,
    "Top 3 customers by total paid amount.": """
        SELECT c.id, c.name, sum(o.total_amount) AS total_paid
          FROM customers c
          JOIN orders o ON o.customer_id = c.id
         WHERE o.status = 'paid'
         GROUP BY c.id, c.name
         ORDER BY total_paid DESC
         LIMIT 3
    """,
}


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
        source = REFERENCE_SQL if answers is None else answers
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
