"""Turn a question plus a schema into a prompt, and clean up what comes back.

The prompt carries three things: the live schema, the rules the SQL must obey,
and a few worked examples. The examples are deliberately not questions from the
evaluation set, so the reported accuracy is not measuring answers that were
handed to the model in its own prompt.
"""

from __future__ import annotations

import re

from .providers.base import LLMProvider

ROLE = (
    "You translate questions about a SQLite database into a single SQL query."
)

RULES = """Rules:
- Return one SELECT statement and nothing else.
- No explanation, no commentary, no markdown fences, no SQL comments.
- Use only the tables and columns listed in the schema above.
- Prefer explicit JOIN ... ON over comma joins.
- Give every aggregate an alias, for example sum(total_amount) AS total_revenue.
- This is SQLite. Use strftime for dates: strftime('%Y-%m', order_date) for a
  month and strftime('%Y', order_date) for a year. EXTRACT and DATE_TRUNC do
  not exist here."""

# One example per shape the model needs: ordering with a limit, an explicit
# join, a grouped aggregate with an alias, and a date filter via strftime.
EXAMPLES = [
    (
        "List the 5 most expensive products.",
        "SELECT name, unit_price FROM products ORDER BY unit_price DESC LIMIT 5",
    ),
    (
        "Which product names appear in order 42?",
        "SELECT p.name FROM order_items i "
        "JOIN products p ON p.id = i.product_id WHERE i.order_id = 42",
    ),
    (
        "What is the total budget per platform?",
        "SELECT platform, sum(budget) AS total_budget FROM campaigns "
        "GROUP BY platform ORDER BY total_budget DESC",
    ),
    (
        "How many ad clicks happened in July 2026?",
        "SELECT count(*) AS click_count FROM ad_clicks "
        "WHERE strftime('%Y-%m', clicked_at) = '2026-07'",
    ),
]


def build_prompt(question: str, schema_block: str) -> str:
    """The generation prompt. The real question is always the last one."""
    parts = [ROLE, "", "Schema:", schema_block, "", RULES, "", "Examples:"]
    for example_question, example_sql in EXAMPLES:
        parts.append(f"Question: {example_question}")
        parts.append(f"SQL: {example_sql}")
    parts.append("")
    parts.append(f"Question: {question}")
    parts.append("SQL:")
    return "\n".join(parts)


def build_correction_prompt(
    question: str, schema_block: str, failed_sql: str, error: str
) -> str:
    """The retry prompt, used after the database rejected the first attempt.

    The error text is the useful part: it usually names the column or table
    that does not exist. The real question stays last, as in build_prompt.
    """
    return "\n".join(
        [
            ROLE,
            "",
            "Schema:",
            schema_block,
            "",
            "Your previous query failed.",
            "",
            "Previous SQL:",
            failed_sql,
            "",
            "Database error:",
            error,
            "",
            "Rewrite the query so it runs. Fix only what the error describes.",
            RULES,
            "",
            f"Question: {question}",
            "SQL:",
        ]
    )


FENCE = re.compile(r"```[a-zA-Z]*\n?(.*?)```", re.DOTALL)


def clean_sql(text: str) -> str:
    """Strip the wrapping a model puts around SQL: fences, labels, semicolon."""
    text = text.strip()
    match = FENCE.search(text)
    if match:
        text = match.group(1)
    text = text.strip()
    # A leading "sql" line survives an unclosed fence.
    if text[:3].lower() == "sql" and (len(text) == 3 or text[3] in " \n\t:"):
        text = text[3:].lstrip(": \n\t")
    return text.strip().rstrip(";").strip()


def generate(question: str, schema_block: str, provider: LLMProvider) -> str:
    """Ask the provider for SQL and return it ready for validation."""
    return clean_sql(provider.generate_sql(build_prompt(question, schema_block)))


def correct(
    question: str,
    schema_block: str,
    failed_sql: str,
    error: str,
    provider: LLMProvider,
) -> str:
    """Ask the provider to fix SQL the database rejected."""
    return clean_sql(
        provider.generate_sql(
            build_correction_prompt(question, schema_block, failed_sql, error)
        )
    )
