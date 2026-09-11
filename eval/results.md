# Evaluation results

Execution accuracy of the agent on the questions in `eval/questions.jsonl`. A
question counts as correct when the rows returned by the agent's SQL match the
rows returned by the reference SQL: same number of columns, same rows,
order-insensitive unless the question asks for a ranking, numbers within 0.01.
SQL text is never compared, because two different queries can be equally
correct.

Each section is one run of `python -m eval.run_eval --provider <name>`.
Running a provider again replaces its section and leaves the others alone.

## mock

- Provider: mock
- Model: none
- Date: 2026-09-11
- Questions: 25
- Execution accuracy: 25/25 (100.0%)
- Needed a self-correction: 0
- Rejected by guardrails: 0
- Failed with a database error, timeout, or provider error: 0
- Elapsed: 0.1 seconds

The mock provider returns the reference SQL for every question, so this run validates the harness, not model quality.

| Category | Correct | Total | Accuracy |
|---|---|---|---|
| simple | 5 | 5 | 100.0% |
| join | 5 | 5 | 100.0% |
| aggregate | 5 | 5 | 100.0% |
| date | 5 | 5 | 100.0% |
| hard | 5 | 5 | 100.0% |

| Id | Category | Result | Corrections | Note |
|---|---|---|---|---|
| simple_01 | simple | PASS | 0 |  |
| simple_02 | simple | PASS | 0 |  |
| simple_03 | simple | PASS | 0 |  |
| simple_04 | simple | PASS | 0 |  |
| simple_05 | simple | PASS | 0 |  |
| join_01 | join | PASS | 0 |  |
| join_02 | join | PASS | 0 |  |
| join_03 | join | PASS | 0 |  |
| join_04 | join | PASS | 0 |  |
| join_05 | join | PASS | 0 |  |
| aggregate_01 | aggregate | PASS | 0 |  |
| aggregate_02 | aggregate | PASS | 0 |  |
| aggregate_03 | aggregate | PASS | 0 |  |
| aggregate_04 | aggregate | PASS | 0 |  |
| aggregate_05 | aggregate | PASS | 0 |  |
| date_01 | date | PASS | 0 |  |
| date_02 | date | PASS | 0 |  |
| date_03 | date | PASS | 0 |  |
| date_04 | date | PASS | 0 |  |
| date_05 | date | PASS | 0 |  |
| hard_01 | hard | PASS | 0 |  |
| hard_02 | hard | PASS | 0 |  |
| hard_03 | hard | PASS | 0 |  |
| hard_04 | hard | PASS | 0 |  |
| hard_05 | hard | PASS | 0 |  |

## groq

- Provider: groq
- Model: openai/gpt-oss-120b
- Date: 2026-09-11
- Questions: 25
- Execution accuracy: 18/25 (72.0%)
- Needed a self-correction: 0
- Rejected by guardrails: 0
- Failed with a database error, timeout, or provider error: 0
- Elapsed: 123.9 seconds

| Category | Correct | Total | Accuracy |
|---|---|---|---|
| simple | 5 | 5 | 100.0% |
| join | 4 | 5 | 80.0% |
| aggregate | 3 | 5 | 60.0% |
| date | 4 | 5 | 80.0% |
| hard | 2 | 5 | 40.0% |

| Id | Category | Result | Corrections | Note |
|---|---|---|---|---|
| simple_01 | simple | PASS | 0 |  |
| simple_02 | simple | PASS | 0 |  |
| simple_03 | simple | PASS | 0 |  |
| simple_04 | simple | PASS | 0 |  |
| simple_05 | simple | PASS | 0 |  |
| join_01 | join | FAIL | 0 | row count 87 vs expected 51 |
| join_02 | join | PASS | 0 |  |
| join_03 | join | PASS | 0 |  |
| join_04 | join | PASS | 0 |  |
| join_05 | join | PASS | 0 |  |
| aggregate_01 | aggregate | FAIL | 0 | row count 0 vs expected 2 |
| aggregate_02 | aggregate | FAIL | 0 | expected row 1 not found in result |
| aggregate_03 | aggregate | PASS | 0 |  |
| aggregate_04 | aggregate | PASS | 0 |  |
| aggregate_05 | aggregate | PASS | 0 |  |
| date_01 | date | PASS | 0 |  |
| date_02 | date | PASS | 0 |  |
| date_03 | date | FAIL | 0 | column count 2 vs expected 1 |
| date_04 | date | PASS | 0 |  |
| date_05 | date | PASS | 0 |  |
| hard_01 | hard | FAIL | 0 | row count 0 vs expected 1 |
| hard_02 | hard | FAIL | 0 | expected row 1 not found in result |
| hard_03 | hard | FAIL | 0 | row count 0 vs expected 3 |
| hard_04 | hard | PASS | 0 |  |
| hard_05 | hard | PASS | 0 |  |
