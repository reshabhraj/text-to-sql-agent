"""Command line entry point.

    python -m src.cli "How many customers are from Italy?"
    python -m src.cli --provider groq
"""

from __future__ import annotations

import argparse
import sys

from .agent import Agent, AgentResult
from .config import PROVIDERS, ConfigError, load_settings
from .providers import get_provider
from .providers.base import ProviderError

# Guard against a question that legitimately returns hundreds of rows filling
# the terminal. The full count is still reported underneath.
MAX_DISPLAY_ROWS = 50


def _cell(value: object) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def format_table(columns: list[str], rows: list[tuple]) -> str:
    """A plain fixed-width table. No dependencies, readable anywhere."""
    if not columns:
        return "(no columns)"
    if not rows:
        return "(no rows)"

    shown = rows[:MAX_DISPLAY_ROWS]
    body = [[_cell(value) for value in row] for row in shown]
    widths = [len(column) for column in columns]
    for row in body:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))

    lines = [
        "  ".join(column.ljust(widths[index]) for index, column in enumerate(columns)),
        "  ".join("-" * width for width in widths),
    ]
    lines.extend(
        "  ".join(cell.ljust(widths[index]) for index, cell in enumerate(row))
        for row in body
    )
    if len(rows) > len(shown):
        lines.append(f"... {len(rows) - len(shown)} more rows not shown")
    return "\n".join(lines)


def render(result: AgentResult) -> str:
    """Everything worth printing for one answered question."""
    lines = []
    if result.sql:
        lines.append("SQL used:")
        lines.append(f"  {result.sql}")
        lines.append("")

    if result.rejected_reason:
        lines.append(f"Refused to run this query: {result.rejected_reason}")
    elif result.error:
        label = "Timed out" if result.timed_out else "Query failed"
        lines.append(f"{label}: {result.error}")
    else:
        lines.append(format_table(result.columns, result.rows))
        lines.append("")
        footer = f"{len(result.rows)} row{'' if len(result.rows) == 1 else 's'}"
        if result.truncated:
            footer += " (capped)"
        footer += f", {result.attempts} correction"
        footer += "" if result.attempts == 1 else "s"
        footer += f", provider: {result.provider}"
        lines.append(footer)
    return "\n".join(lines)


def ask_and_print(agent: Agent, question: str) -> int:
    try:
        result = agent.ask(question)
    except ProviderError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(render(result))
    return 0 if result.ok else 1


def interactive(agent: Agent) -> int:
    print(f"Connected with the {agent.provider.name} provider. Type exit to quit.")
    while True:
        try:
            question = input("\nquestion> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not question:
            continue
        if question.lower() in {"exit", "quit"}:
            return 0
        ask_and_print(agent, question)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.cli",
        description="Ask the sample database a question in plain English.",
    )
    parser.add_argument(
        "question",
        nargs="?",
        help="the question to answer. Omit it for an interactive session.",
    )
    parser.add_argument(
        "--provider",
        choices=PROVIDERS,
        help="which model to use. Defaults to LLM_PROVIDER, or mock.",
    )
    args = parser.parse_args(argv)

    try:
        settings = load_settings(provider_override=args.provider)
        agent = Agent(settings, get_provider(settings))
    except ConfigError as exc:
        # One sentence, no stack trace: these are all things the reader can fix.
        print(str(exc), file=sys.stderr)
        return 1

    if args.question:
        return ask_and_print(agent, args.question)
    return interactive(agent)


if __name__ == "__main__":
    sys.exit(main())
