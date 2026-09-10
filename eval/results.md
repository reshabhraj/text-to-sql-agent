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
- Date: 2026-09-10
- Questions: 25
- Execution accuracy: 25/25 (100.0%)
- Needed a self-correction: 0
- Rejected by guardrails: 0
- Failed with a database error, timeout, or provider error: 0
- Elapsed: 0.2 seconds

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
