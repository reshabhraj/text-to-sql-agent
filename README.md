# text-to-sql-agent

[![CI](https://github.com/reshabhraj/text-to-sql-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/reshabhraj/text-to-sql-agent/actions/workflows/ci.yml)

Ask a database questions in plain English. The agent generates SQL, validates it for safety, executes it read-only, self-corrects on errors, and reports its own accuracy on a fixed evaluation set.

## What it does

You ask a question in English. The agent reads the live database schema, prompts an LLM for a single SELECT statement, validates that statement against a set of rules before anything touches the database, runs it on a read-only connection, and hands back rows. If the database rejects the query, the error goes back to the model and the rewritten query is validated again from scratch.

```
$ python -m src.cli --provider groq "How many customers are from Italy?"

SQL used:
  SELECT COUNT(*) AS customer_count FROM customers WHERE country = 'Italy' LIMIT 500

customer_count
--------------
14

1 row, 0 corrections, provider: groq
```

## Why this exists

I built a text-to-SQL layer for a performance marketing agency so non-technical stakeholders could query live campaign and revenue metrics in plain English instead of waiting on an analyst. That system is client work and cannot be published. This repository is a clean, original, fully runnable version of the same idea, built from scratch on synthetic data, so the design and the engineering can actually be inspected.

## Architecture

```
question
   |
   v
schema introspection ......... live tables, columns, foreign keys
   |
   v
prompt ....................... schema block + rules + 4 few-shot examples
   |
   v
LLM provider ................. mock | groq | gemini | anthropic
   |
   v
guardrails ................... reject -> refuse, nothing executes
   |  pass
   v
read-only execution .......... file:...?mode=ro, timeout, row cap
   |
   +-- database error -> correction prompt -> back to guardrails
   |                     (max 2 attempts)
   v
columns + rows
```

| Component | Responsibility |
|---|---|
| `src/config.py` | Loads `.env`, resolves the provider, fails with one clear sentence when a key or model is missing. |
| `src/schema_introspect.py` | Reads tables, columns and foreign keys from the live database and renders the schema block for the prompt. |
| `src/generator.py` | Builds the prompt (schema, rules, few-shot examples), calls the provider, strips code fences from the reply. |
| `src/guardrails.py` | Validates the generated SQL against the rules below. Returns `ValidationResult(ok, sql, reason)`. |
| `src/executor.py` | Opens SQLite read-only, applies a statement timeout and a row cap, returns columns and rows. |
| `src/agent.py` | Orchestrates the flow and owns the self-correction loop. Returns `AgentResult`. |
| `src/cli.py` | One-shot and interactive command line. |
| `src/providers/base.py` | The `LLMProvider` interface: `name` and `generate_sql(prompt) -> str`. |
| `src/providers/http.py` | Shared HTTP POST helper that turns transport and HTTP errors into one readable `ProviderError`. |
| `src/providers/mock_provider.py` | Deterministic provider backed by the evaluation set. No network, no key. |
| `src/providers/groq_provider.py` | Groq chat completions. |
| `src/providers/gemini_provider.py` | Google AI Studio (Gemini) `generateContent`. |
| `src/providers/anthropic_provider.py` | Anthropic Messages API. |
| `eval/run_eval.py` | Runs the question set, compares result sets, writes `eval/results.md`. |

### What the guardrails actually reject

Validation uses `sqlglot` to parse the SQL into an AST, so the checks run against structure rather than string matching. In order: the query must be non-empty, tokenizable and parseable; it must contain no SQL comments; it must be exactly one statement; its root must be a `SELECT`, which allows `WITH ... SELECT` but rejects `UNION`, `EXCEPT` and `INTERSECT`; no write or DDL node (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `CREATE`, `PRAGMA`, `ATTACH`) may appear anywhere in the tree, including inside a subquery or CTE; every table reference must be a plain, unqualified name drawn from the introspected allowlist, with CTE names exempt. If the query has no `LIMIT`, one is appended.

Rejecting set operations is stricter than it strictly needs to be. A `UNION` of two `SELECT`s is still read-only. It is rejected because the root-node check is the same check that stops a `DELETE`, and I preferred one simple rule I can reason about over a special case that widens the surface.

## Design decisions

**Guardrails run before execution, and corrected queries go back through them.** An LLM will occasionally emit a write statement or reference a table that does not exist. One bad query costs far more than validating every query does. The self-correction path is the dangerous one, because it is tempting to trust SQL the model has already "fixed", so a corrected query re-enters validation from the top rather than skipping to execution.

**The read-only connection is a second, independent layer.** The guardrails are code I wrote, and code I wrote can have bugs. The database itself is opened with SQLite's `mode=ro` URI, so a write that somehow passed validation still fails at the connection. The test for this runs `INSERT`, `UPDATE` and `DELETE` through the executor and then re-counts the rows over a separate writable connection to prove nothing changed.

**Execution accuracy, not SQL string matching.** Two different queries can be equally correct, so comparing query text measures style, not correctness. A question counts as correct when the rows its SQL returns match the rows the reference SQL returns: same column count, same rows, order-insensitive unless the question asks for a ranking, numbers within 0.01. Column names are ignored.

**Self-correction is capped at 2 attempts.** A database error carries real signal, and feeding it back fixes genuine mistakes. Unbounded retries would hide systematic failures behind eventual success and turn one bad question into an unbounded bill. Only database errors trigger a retry: a guardrail rejection is terminal, and a timeout is never retried.

**A provider interface with a mock.** Tests and CI cannot depend on an external API being up, having quota, or returning the same thing twice, and the evaluation harness itself needs to be testable. The mock makes the whole pipeline deterministic and free. Multiple real providers mean the evaluation compares models instead of quoting one number as if it were the truth about LLMs.

**Schema introspection at runtime, not a hand-written schema string.** The prompt is generated from the database as it currently is, so the schema in the prompt cannot drift out of sync with the schema in the database.

## Evaluation

25 questions in `eval/questions.jsonl`, five each in `simple`, `join`, `aggregate`, `date` and `hard`. Every reference query is itself tested: a parametrized test asserts each one passes the guardrails, executes, and returns at least one row. Another test asserts no evaluation question duplicates a few-shot example from the prompt.

**Groq, `openai/gpt-oss-120b`, 2026-09-11**

| Category | Correct | Total | Accuracy |
|---|---|---|---|
| simple | 5 | 5 | 100.0% |
| join | 4 | 5 | 80.0% |
| aggregate | 3 | 5 | 60.0% |
| date | 4 | 5 | 80.0% |
| hard | 2 | 5 | 40.0% |
| **overall** | **18** | **25** | **72.0%** |

No guardrail rejections, no provider errors, and no question needed a self-correction. Every failure was valid SQL that ran successfully and returned the wrong rows.

**Mock provider: 25/25.** The mock returns the reference SQL for every question, so this run validates the harness, not model quality. CI enforces it at 100 percent, which is what makes the number meaningful: if the comparison logic breaks, CI fails.

Gemini numbers are not here yet. Runs on 2026-09-11 exhausted the free-tier daily quota partway through, and a run where a third of the questions returned HTTP 429 measures Google's rate limiter, not the model. Those numbers will be added after a clean run rather than published with an asterisk.

### What Groq actually got wrong

Three of the seven failures share one root cause, and it is the interesting one. Asked for the top 3 customers by total paid amount, the model produced:

```sql
SELECT c.id, c.name, SUM(p.amount) AS total_paid
FROM payments AS p
JOIN orders AS o ON o.id = p.order_id
JOIN customers AS c ON c.id = o.customer_id
WHERE p.status = 'paid'
GROUP BY c.id, c.name ORDER BY total_paid DESC LIMIT 3
```

The joins are right. The filter is not: `payments.status` is always `'completed'` in this data, and `'paid'` is a value of `orders.status`. Both tables have a `status` column, and the schema block sends column names and types but not the values a `CHECK` constraint allows, so the model had no way to know which vocabulary belonged to which column. The query is valid SQL, it executes without error, and it returns zero rows. Nothing raises, so the self-correction loop never fires. The same mistake sank both campaign attribution questions, where the model got the harder part, joining `orders` to `ad_clicks` on `session_id`, completely right.

That points at a fix in the prompt, not the model: render allowed values into the schema block. It is the first item under next steps.

Of the remaining four failures, one is my fault rather than the model's. `date_03` asks for revenue "by order date", which can be read as grouped by date or filtered by date. The model grouped, the reference filters, and the harness counted it wrong. An ambiguous question is a bug in an evaluation set.

## Run it

Python 3.11 or newer. No API key is needed to run the tests or the mock evaluation.

**Windows (PowerShell)**

```powershell
git clone https://github.com/reshabhraj/text-to-sql-agent.git
cd text-to-sql-agent
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m db.seed
python -m src.cli "How many customers are from Italy?"
```

**macOS / Linux**

```bash
git clone https://github.com/reshabhraj/text-to-sql-agent.git
cd text-to-sql-agent
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m db.seed
python -m src.cli "How many customers are from Italy?"
```

`python -m db.seed` is required. The database is generated, not committed. It is deterministic: the same seed produces the same 200 customers, 30 products, 8 campaigns, 3000 ad clicks, 800 orders, 1988 order items and 574 payments, spanning January to August 2026.

Run the tests and the evaluation:

```bash
python -m pytest
python -m eval.run_eval --provider mock --fail-under 100
```

### Using a real model

The default provider is `mock`, which answers from a lookup table built out of the evaluation questions and returns `SELECT 1` for anything it does not recognise. It exists to make tests and CI deterministic. To ask your own questions you need a real provider, and both of these have a free tier with no credit card:

- **Groq**: sign up at `console.groq.com`, create an API key.
- **Gemini**: sign in at `aistudio.google.com`, create an API key.

```bash
cp .env.example .env
```

Put the key in `.env` next to `GROQ_API_KEY` or `GEMINI_API_KEY`, then:

```bash
python -m src.cli --provider groq "Which campaign drove the most paid revenue?"
python -m eval.run_eval --provider groq --pause 4
```

`--pause` throttles the evaluation between questions. Free tiers are tight and there is no retry logic, so leave it in.

Interactive mode is `python -m src.cli` with no question.

## The sample database

Synthetic, generated from a fixed seed, no real people or companies. Seven tables: `customers`, `products`, `campaigns`, `ad_clicks`, `orders`, `order_items`, `payments`.

The detail worth pointing at is `session_id`, which appears on both `ad_clicks` and `orders` and is how a click is tied to the order it produced. Roughly 60 percent of orders carry one. This is the click-to-payment attribution pattern from the real system, and it is what the `hard` questions exercise. It is deliberately not a declared foreign key, which means it never appears in the schema block, which in turn means the evaluation questions have to describe the join in words. So those questions measure whether a model can execute an attribution rule it has been told, not whether it can discover one.

## Tests and CI

125 tests across 7 files, a good share of them parametrized so each guardrail rule and each reference query is its own case. They cover the guardrails rule by rule, read-only enforcement and the row cap, schema introspection, the agent end to end against the mock, the CLI, the comparison metric, and the integrity of the evaluation set. The test fixtures build their own database in a temporary directory and construct settings directly, so nothing in a developer's `.env` can reach the suite.

CI runs on every push and pull request: Python 3.11 on Ubuntu, install, seed, pytest, then the mock evaluation gated at 100 percent. It requires no API key. There is no lint or type-check step.

## Limitations

- **No multi-turn memory.** Every question is independent. "And how about last month?" will not work.
- **The PostgreSQL backend is a stub.** `DATABASE_URL` will open a read-only psycopg connection, but the guardrails parse in the SQLite dialect and the prompt explicitly instructs the model to use `strftime`, so date handling would break. It is untested and should be treated as unfinished rather than optional.
- **25 questions is a small evaluation set,** and at least one of them is ambiguously worded. Differences of a question or two between providers are noise.
- **No retry or backoff on provider errors.** A 429 or 503 is recorded as a failed question. The `--pause` flag is the only throttle, which is why the Gemini run could not be completed.
- **No query cost estimation.** Nothing stops the model from writing an expensive join; the timeout and row cap are the only backstop.
- **Coverage gaps.** The three real provider clients, the PostgreSQL branches, and the interactive CLI loop have no automated tests. Everything exercised by CI runs against the mock or against SQLite.

## Next steps

- Render `CHECK` constraint values into the schema block, which addresses the single largest cause of failures above.
- Retry with exponential backoff on 429 and 503, so a free-tier evaluation run can finish.
- Add the Gemini numbers once quota resets, and Anthropic alongside them.
- Grow the evaluation set and fix the ambiguous question.
- Finish or remove the PostgreSQL path rather than leaving it half-built.
- A small web UI, since the people this was originally built for do not use a terminal.

## Built with

Built with Claude Code as the implementation partner. The architecture, guardrail design, evaluation methodology, and iteration decisions are mine.
