"""The loop that turns a question into an answer.

Order matters here: generate, validate, then execute. Validation always runs
before the database sees anything, and a query the model rewrote after an
error goes through validation again rather than around it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import Settings
from .executor import ExecutionError, QueryResult, QueryTimeout, execute
from .generator import correct, generate
from .guardrails import validate
from .providers.base import LLMProvider
from .schema_introspect import SchemaInfo, introspect

# The brief's cap. Error messages carry real signal, so one or two retries
# recover a lot of near misses, but retrying forever would just hide a model
# that is systematically wrong about this schema.
MAX_CORRECTIONS = 2


@dataclass(frozen=True)
class AgentResult:
    """What one question produced.

    attempts is the number of correction round-trips sent to the provider.
    0 means the first query passed validation and ran. The maximum is
    MAX_CORRECTIONS, so a question costs at most three generations.
    """

    question: str
    provider: str
    sql: str = ""
    columns: list[str] = field(default_factory=list)
    rows: list[tuple] = field(default_factory=list)
    attempts: int = 0
    rejected_reason: str | None = None
    error: str | None = None
    timed_out: bool = False
    truncated: bool = False

    @property
    def ok(self) -> bool:
        return self.rejected_reason is None and self.error is None


class Agent:
    def __init__(self, settings: Settings, provider: LLMProvider) -> None:
        self.settings = settings
        self.provider = provider
        # Introspected once and reused: the schema does not change under us
        # mid-run, and every question needs the same block.
        self.schema: SchemaInfo = introspect(settings)
        self.schema_block = self.schema.render()
        self.allowed_tables = self.schema.table_names()

    def _result(self, question: str, **kwargs) -> AgentResult:
        return AgentResult(question=question, provider=self.provider.name, **kwargs)

    def ask(self, question: str) -> AgentResult:
        sql = generate(question, self.schema_block, self.provider)
        attempts = 0

        while True:
            checked = validate(sql, self.allowed_tables, self.settings.row_limit)
            if not checked.ok:
                # A rejection ends the run. The model produced something
                # outside the read-only contract, and asking it to try again
                # would mean deciding which violations are worth a second
                # chance. Nothing that failed validation is ever executed.
                return self._result(
                    question, sql=sql, attempts=attempts, rejected_reason=checked.reason
                )

            try:
                result: QueryResult = execute(checked.sql, self.settings)
            except QueryTimeout as exc:
                # Not a correctable mistake. The same query would time out
                # again and spend the remaining budget doing it.
                return self._result(
                    question,
                    sql=checked.sql,
                    attempts=attempts,
                    error=str(exc),
                    timed_out=True,
                )
            except ExecutionError as exc:
                if attempts >= MAX_CORRECTIONS:
                    return self._result(
                        question, sql=checked.sql, attempts=attempts, error=str(exc)
                    )
                attempts += 1
                sql = correct(
                    question,
                    self.schema_block,
                    checked.sql,
                    str(exc),
                    self.provider,
                )
                continue

            return self._result(
                question,
                sql=checked.sql,
                columns=result.columns,
                rows=result.rows,
                attempts=attempts,
                truncated=result.truncated,
            )
