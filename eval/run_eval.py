"""Measure the agent's execution accuracy on a fixed question set.

    python -m eval.run_eval                                 # provider from .env
    python -m eval.run_eval --provider groq --pause 4       # a real model
    python -m eval.run_eval --provider mock --fail-under 100   # what CI runs

For every question the agent's SQL and the reference SQL are both executed and
their result sets compared: same number of columns, same rows, order-insensitive
unless the question asks for a ranking, numbers within 0.01. SQL text is never
compared, because two different queries can be equally correct.

The mock provider answers with the reference SQL itself, so a mock run scores
100 percent by construction. It proves the harness works, not that any model
does, and the results file says so.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from src.agent import Agent
from src.config import PROVIDERS, ConfigError, Settings, load_settings
from src.executor import ExecutionError, QueryResult, QueryTimeout, execute
from src.providers import ProviderError, get_provider

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_QUESTIONS = ROOT / "eval" / "questions.jsonl"
DEFAULT_RESULTS = ROOT / "eval" / "results.md"

CATEGORIES = ("simple", "join", "aggregate", "date", "hard")
REQUIRED_FIELDS = ("id", "category", "question", "reference_sql", "ordered")

# The brief's numeric tolerance. Sums of two-decimal amounts pick up float
# noise around the eleventh decimal; nothing that matters is smaller than this.
TOLERANCE = 0.01
NUM = (int, float)

# A note in the results table is one Markdown cell. Longer than this and the
# table stops being readable; the full message is still on stdout.
MAX_NOTE_LENGTH = 160

MOCK_NOTICE = (
    "The mock provider returns the reference SQL for every question, so this "
    "run validates the harness, not model quality."
)

RESULTS_HEADER = """# Evaluation results

Execution accuracy of the agent on the questions in `eval/questions.jsonl`. A
question counts as correct when the rows returned by the agent's SQL match the
rows returned by the reference SQL: same number of columns, same rows,
order-insensitive unless the question asks for a ranking, numbers within 0.01.
SQL text is never compared, because two different queries can be equally
correct.

Each section is one run of `python -m eval.run_eval --provider <name>`.
Running a provider again replaces its section and leaves the others alone."""


@dataclass(frozen=True)
class Question:
    id: str
    category: str
    question: str
    reference_sql: str
    ordered: bool


@dataclass(frozen=True)
class Outcome:
    """What happened to one question."""

    question: Question
    correct: bool
    attempts: int
    rejected: bool
    failed: bool
    note: str
    seconds: float
    sql: str


@dataclass(frozen=True)
class Summary:
    provider: str
    model: str
    run_date: str
    outcomes: list[Outcome]
    elapsed: float

    @property
    def total(self) -> int:
        return len(self.outcomes)

    @property
    def correct(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.correct)

    @property
    def accuracy(self) -> float:
        return 100.0 * self.correct / self.total if self.total else 0.0

    @property
    def corrected(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.attempts > 0)

    @property
    def rejected(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.rejected)

    @property
    def failed(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.failed)

    def by_category(self) -> list[tuple[str, int, int]]:
        """(category, correct, total) in the fixed category order."""
        seen = [c for c in CATEGORIES if any(o.question.category == c for o in self.outcomes)]
        seen += sorted({o.question.category for o in self.outcomes} - set(CATEGORIES))
        rows = []
        for category in seen:
            group = [o for o in self.outcomes if o.question.category == category]
            rows.append((category, sum(1 for o in group if o.correct), len(group)))
        return rows


# Loading


def load_questions(path: Path = DEFAULT_QUESTIONS) -> list[Question]:
    """Read and check the question file. Problems are one clear sentence."""
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"Question file not found at {path}.")

    questions: list[Question] = []
    seen_ids: set[str] = set()
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            where = f"{path.name} line {line_number}"
            try:
                record = json.loads(line)
            except ValueError as exc:
                raise ConfigError(f"{where} is not valid JSON: {exc}.") from None
            if not isinstance(record, dict):
                raise ConfigError(f"{where} must be a JSON object.")
            missing = [field for field in REQUIRED_FIELDS if field not in record]
            if missing:
                raise ConfigError(f"{where} is missing {', '.join(missing)}.")
            if record["id"] in seen_ids:
                raise ConfigError(f"{where} repeats the id '{record['id']}'.")
            if record["category"] not in CATEGORIES:
                raise ConfigError(
                    f"{where} has category '{record['category']}', "
                    f"expected one of {', '.join(CATEGORIES)}."
                )
            if not isinstance(record["ordered"], bool):
                raise ConfigError(f"{where} needs 'ordered' to be true or false.")
            if not str(record["question"]).strip() or not str(record["reference_sql"]).strip():
                raise ConfigError(f"{where} has an empty question or reference_sql.")
            seen_ids.add(record["id"])
            questions.append(
                Question(
                    id=str(record["id"]),
                    category=record["category"],
                    question=str(record["question"]).strip(),
                    reference_sql=str(record["reference_sql"]).strip(),
                    ordered=record["ordered"],
                )
            )
    if not questions:
        raise ConfigError(f"{path} contains no questions.")
    return questions


# The metric


def cells_match(a: object, b: object) -> bool:
    """One cell against another, with the numeric tolerance.

    Numbers compare numerically, so 574 equals 574.0. When only one side is a
    number the other is parsed, which is how 608.5500000001 matches the text
    '608.55'. Everything else compares as text, so a date is a date whether the
    driver handed it back as a string or not. Both sides are never coerced
    together: that would make '2026' equal 2026.0 for no gain, since the text
    comparison already handles it.
    """
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, NUM) and isinstance(b, NUM):
        return abs(a - b) <= TOLERANCE
    if isinstance(a, NUM) != isinstance(b, NUM):
        try:
            return abs(float(a) - float(b)) <= TOLERANCE
        except (ValueError, TypeError):
            pass
    return str(a) == str(b)


def rows_match(expected: tuple, actual: tuple) -> bool:
    return len(expected) == len(actual) and all(
        cells_match(e, a) for e, a in zip(expected, actual)
    )


def compare_results(
    expected: QueryResult, actual: QueryResult, ordered: bool
) -> tuple[bool, str]:
    """Execution accuracy for one question.

    Column names are ignored: the model may alias an aggregate differently
    and still be right. Column count, row count, and every cell must match.
    Unordered comparison pairs each expected row with one unused actual row,
    so duplicates are counted, not collapsed. Returns (matched, first
    difference), with an empty string when they match.
    """
    if len(expected.columns) != len(actual.columns):
        return False, (
            f"column count {len(actual.columns)} vs expected {len(expected.columns)}"
        )
    if len(expected.rows) != len(actual.rows):
        return False, f"row count {len(actual.rows)} vs expected {len(expected.rows)}"

    if ordered:
        for index, (e, a) in enumerate(zip(expected.rows, actual.rows), start=1):
            if not rows_match(e, a):
                return False, f"row {index} differs"
        return True, ""

    unmatched = list(actual.rows)
    for index, e in enumerate(expected.rows, start=1):
        for position, a in enumerate(unmatched):
            if rows_match(e, a):
                del unmatched[position]
                break
        else:
            return False, f"expected row {index} not found in result"
    return True, ""


# Running


def evaluate_question(agent: Agent, question: Question, settings: Settings) -> Outcome:
    started = time.monotonic()
    try:
        result = agent.ask(question.question)
    except ProviderError as exc:
        return Outcome(
            question, False, 0, False, True, f"provider error: {exc}",
            time.monotonic() - started, "",
        )
    seconds = time.monotonic() - started

    if result.rejected_reason:
        return Outcome(
            question, False, result.attempts, True, False,
            f"rejected by guardrails: {result.rejected_reason}", seconds, result.sql,
        )
    if result.error:
        label = "timed out" if result.timed_out else "database error"
        return Outcome(
            question, False, result.attempts, False, True,
            f"{label}: {result.error}", seconds, result.sql,
        )

    # The reference runs through the same read-only, row-capped executor as
    # the agent's query, so both sides are bounded identically.
    try:
        expected = execute(question.reference_sql, settings)
    except (ExecutionError, QueryTimeout) as exc:
        return Outcome(
            question, False, result.attempts, False, True,
            f"reference SQL failed: {exc}", seconds, result.sql,
        )
    actual = QueryResult(result.columns, result.rows, result.truncated)
    correct, why = compare_results(expected, actual, question.ordered)
    return Outcome(question, correct, result.attempts, False, False, why, seconds, result.sql)


def run(
    agent: Agent,
    questions: list[Question],
    settings: Settings,
    pause: float = 0.0,
    verbose: bool = False,
) -> Summary:
    started = time.monotonic()
    outcomes: list[Outcome] = []
    width = len(str(len(questions)))
    for number, question in enumerate(questions, start=1):
        if pause and number > 1:
            time.sleep(pause)
        outcome = evaluate_question(agent, question, settings)
        outcomes.append(outcome)
        status = "PASS" if outcome.correct else "FAIL"
        line = f"[{number:>{width}}/{len(questions)}] {status} {question.id}"
        if outcome.attempts:
            line += f" ({outcome.attempts} correction{'' if outcome.attempts == 1 else 's'})"
        if outcome.note:
            line += f": {outcome.note}"
        print(line)
        if verbose and outcome.sql:
            print(f"    {outcome.sql}")
    return Summary(
        provider=agent.provider.name,
        model=settings.model or "none",
        run_date=date.today().isoformat(),
        outcomes=outcomes,
        elapsed=time.monotonic() - started,
    )


# Reporting


def clean_note(note: str) -> str:
    """Make a note safe for one Markdown table cell."""
    note = " ".join(note.split()).replace("|", "\\|")
    if len(note) > MAX_NOTE_LENGTH:
        note = note[: MAX_NOTE_LENGTH - 3] + "..."
    return note


def render_section(summary: Summary) -> str:
    """The Markdown for one provider run, without its heading line."""
    lines = [
        f"- Provider: {summary.provider}",
        f"- Model: {summary.model}",
        f"- Date: {summary.run_date}",
        f"- Questions: {summary.total}",
        f"- Execution accuracy: {summary.correct}/{summary.total} ({summary.accuracy:.1f}%)",
        f"- Needed a self-correction: {summary.corrected}",
        f"- Rejected by guardrails: {summary.rejected}",
        f"- Failed with a database error, timeout, or provider error: {summary.failed}",
        f"- Elapsed: {summary.elapsed:.1f} seconds",
        "",
    ]
    if summary.provider == "mock":
        lines += [MOCK_NOTICE, ""]

    lines += ["| Category | Correct | Total | Accuracy |", "|---|---|---|---|"]
    for category, correct, total in summary.by_category():
        share = 100.0 * correct / total if total else 0.0
        lines.append(f"| {category} | {correct} | {total} | {share:.1f}% |")
    lines.append("")

    lines += ["| Id | Category | Result | Corrections | Note |", "|---|---|---|---|---|"]
    for outcome in summary.outcomes:
        lines.append(
            f"| {outcome.question.id} | {outcome.question.category} | "
            f"{'PASS' if outcome.correct else 'FAIL'} | {outcome.attempts} | "
            f"{clean_note(outcome.note)} |"
        )
    return "\n".join(lines)


def split_sections(text: str) -> tuple[list[str], dict[str, str]]:
    """Provider sections of an existing results file, keyed by heading."""
    order: list[str] = []
    bodies: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            if current not in bodies:
                order.append(current)
            bodies[current] = []
        elif current is not None:
            bodies[current].append(line)
    return order, {name: "\n".join(lines).strip("\n") for name, lines in bodies.items()}


def update_results_file(path: Path, summary: Summary) -> None:
    """Write or replace this provider's section, keeping every other one."""
    path = Path(path)
    order: list[str] = []
    sections: dict[str, str] = {}
    if path.exists():
        order, sections = split_sections(path.read_text(encoding="utf-8"))
    if summary.provider not in sections:
        order.append(summary.provider)
    sections[summary.provider] = render_section(summary)

    parts = [RESULTS_HEADER]
    parts += [f"## {name}\n\n{sections[name]}" for name in order]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n\n".join(parts) + "\n", encoding="utf-8")


def print_summary(summary: Summary) -> None:
    print()
    print(f"Provider: {summary.provider} (model: {summary.model})")
    print(
        f"Execution accuracy: {summary.correct}/{summary.total} ({summary.accuracy:.1f}%)"
    )
    for category, correct, total in summary.by_category():
        print(f"  {category:<10} {correct}/{total}")
    print(f"Needed a self-correction: {summary.corrected}")
    print(f"Rejected by guardrails: {summary.rejected}")
    print(f"Failed with a database error, timeout, or provider error: {summary.failed}")
    print(f"Elapsed: {summary.elapsed:.1f} seconds")


def main(argv: list[str] | None = None) -> int:
    # A Windows console may not be able to print a model-invented identifier
    # that came back in an error message. Replace rather than crash.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    parser = argparse.ArgumentParser(
        prog="python -m eval.run_eval",
        description="Score the agent on the fixed question set by execution accuracy.",
    )
    parser.add_argument(
        "--provider", choices=PROVIDERS, help="which model to use. Defaults to LLM_PROVIDER, or mock."
    )
    parser.add_argument(
        "--questions", type=Path, default=DEFAULT_QUESTIONS, help="question file (JSON lines)"
    )
    parser.add_argument(
        "--out", type=Path, default=DEFAULT_RESULTS, help="Markdown results file to update"
    )
    parser.add_argument(
        "--fail-under",
        type=float,
        default=None,
        metavar="PERCENT",
        help="exit with status 1 when accuracy is below this percentage",
    )
    parser.add_argument(
        "--pause",
        type=float,
        default=0.0,
        metavar="SECONDS",
        help="wait between questions, for free-tier rate limits",
    )
    parser.add_argument("--verbose", action="store_true", help="also print the SQL used")
    args = parser.parse_args(argv)

    try:
        settings = load_settings(provider_override=args.provider)
        agent = Agent(settings, get_provider(settings))
        questions = load_questions(args.questions)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    summary = run(agent, questions, settings, pause=args.pause, verbose=args.verbose)
    print_summary(summary)
    update_results_file(args.out, summary)
    print(f"Results written to {args.out}")

    if args.fail_under is not None and summary.accuracy < args.fail_under:
        print(
            f"Accuracy {summary.accuracy:.1f}% is below the required {args.fail_under:g}%.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
