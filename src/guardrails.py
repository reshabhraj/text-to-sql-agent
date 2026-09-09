"""Validate generated SQL before it is allowed anywhere near the database.

A language model will occasionally write a statement that deletes data or
reads a table that does not exist. Checking first is cheap; one bad query is
not. Everything here runs on the parsed syntax tree rather than on the text,
because text matching is easy to slip past.

This is the first of two layers. The second is the read-only connection in
executor.py, which holds even if something here is wrong.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError, TokenError

DIALECT = "sqlite"
DEFAULT_ROW_LIMIT = 500

# Anything that writes, changes structure, or reaches outside the query.
# The root check already rejects these; walking the tree as well means a
# statement hidden inside a subquery cannot ride along with a SELECT.
FORBIDDEN = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Alter,
    exp.Create,
    exp.Pragma,
    exp.Attach,
    exp.Command,
)

READABLE_NAMES = {
    exp.Insert: "an INSERT",
    exp.Update: "an UPDATE",
    exp.Delete: "a DELETE",
    exp.Drop: "a DROP",
    exp.Alter: "an ALTER",
    exp.Create: "a CREATE",
    exp.Pragma: "a PRAGMA",
    exp.Attach: "an ATTACH",
    exp.Command: "an unsupported command",
    exp.Union: "a UNION",
    exp.Except: "an EXCEPT",
    exp.Intersect: "an INTERSECT",
}


@dataclass(frozen=True)
class ValidationResult:
    """ok says whether the SQL may run. sql is the version to run, which may
    carry an added LIMIT. reason explains a rejection and is None when ok."""

    ok: bool
    sql: str
    reason: str | None = None


def _describe(node: exp.Expression) -> str:
    for kind, label in READABLE_NAMES.items():
        if type(node) is kind:
            return label
    return f"a {type(node).__name__.upper()} statement"


def _first_line(error: Exception) -> str:
    """A short, single-line description of a parser or tokenizer failure.

    sqlglot's own message embeds a full token dump, which is noise for anyone
    reading the CLI, so the structured description is preferred where it
    exists.
    """
    message = ""
    details = getattr(error, "errors", None)
    if details:
        first = details[0]
        description = str(first.get("description", "")).strip()
        # The description often ends with a raw token dump. Cut it there.
        description = description.split(" but got <Token")[0].strip()
        line, col = first.get("line"), first.get("col")
        if description:
            message = description
            if line is not None and col is not None:
                message = f"{description} at line {line}, column {col}"
    if not message:
        message = str(error).strip().splitlines()[0].strip()
    message = " ".join(message.split())
    return message if len(message) <= 120 else message[:117] + "..."


def validate(
    sql: str,
    allowed_tables: Iterable[str],
    row_limit: int = DEFAULT_ROW_LIMIT,
) -> ValidationResult:
    """Check one generated query. Returns the SQL to run, or a reason not to."""
    text = (sql or "").strip()
    if not text:
        return ValidationResult(False, sql, "the query is empty")

    # 1. Comments. Checked on tokens, not on the raw text: a text scan for --
    # rejects a legitimate string such as '/sale--summer', and the seed data
    # contains landing pages of exactly that shape.
    try:
        tokens = sqlglot.tokenize(text, read=DIALECT)
    except TokenError as exc:
        return ValidationResult(False, sql, f"could not parse the SQL: {_first_line(exc)}")
    if any(token.comments for token in tokens):
        return ValidationResult(False, sql, "SQL comments are not allowed")

    # 2. Parse.
    try:
        statements = [s for s in sqlglot.parse(text, read=DIALECT) if s is not None]
    except ParseError as exc:
        return ValidationResult(False, sql, f"could not parse the SQL: {_first_line(exc)}")
    if not statements:
        return ValidationResult(False, sql, "the query is empty")

    # 3. One statement only. This is what stops semicolon chaining.
    if len(statements) > 1:
        return ValidationResult(
            False, sql, f"only one statement is allowed, found {len(statements)}"
        )
    root = statements[0]

    # 4. It must be a SELECT. A WITH ... SELECT parses as a Select carrying a
    # with clause, so common table expressions pass here unchanged. Set
    # operations (UNION, EXCEPT, INTERSECT) parse as their own types and are
    # rejected by this same check, which is why there is no separate rule for
    # them: EXCEPT and INTERSECT do not subclass UNION, so a UNION-only test
    # would quietly miss two of the three.
    if not isinstance(root, exp.Select):
        return ValidationResult(
            False, sql, f"only SELECT queries are allowed, this is {_describe(root)}"
        )
    for node in root.walk():
        if isinstance(node, FORBIDDEN):
            return ValidationResult(
                False, sql, f"only SELECT queries are allowed, found {_describe(node)}"
            )

    # 5. Every table must be one the database actually has. Names introduced
    # by a WITH clause are the exception: they are defined by the query itself.
    cte_names = {cte.alias_or_name.lower() for cte in root.find_all(exp.CTE)}
    allowed = {name.lower() for name in allowed_tables}
    for table in root.find_all(exp.Table):
        # An empty name is never skipped. SELECT * FROM pragma_table_info(...)
        # produces a table node with no name at all, and treating that as
        # "nothing to check" would open a way around both this allowlist and
        # the PRAGMA rule above.
        if not table.name or not isinstance(table.this, exp.Identifier):
            return ValidationResult(
                False, sql, "table references must be plain table names"
            )
        if table.db or table.catalog:
            return ValidationResult(
                False,
                sql,
                f"'{table.sql(dialect=DIALECT)}' is qualified; use the table name alone",
            )
        name = table.name.lower()
        if name in cte_names:
            continue
        if name not in allowed:
            return ValidationResult(False, sql, f"unknown table '{table.name}'")

    # 6. Cap the result size when the query does not. An existing LIMIT is
    # left exactly as written, whatever its value: the executor is what
    # actually bounds the rows read, and rewriting the user's query would
    # change its meaning.
    if not root.args.get("limit"):
        root = root.limit(row_limit)

    return ValidationResult(True, root.sql(dialect=DIALECT), None)
