# Evals

Evals ask the real agent fixed questions whose answers we know from the sample data, and score
the answers automatically. Tests (`tests/`) check the code; evals check the AI's behaviour.

## Run

```powershell
.venv\Scripts\python.exe evals\run_evals.py                  # next 5 cases, most important first
.venv\Scripts\python.exe evals\run_evals.py --limit 3 --model google_genai:gemini-3.8-flash
.venv\Scripts\python.exe evals\run_evals.py --only cost-total,cost-why-up --rerun
.venv\Scripts\python.exe evals\run_evals.py --judge          # also score answers 1-5 (more quota)
.venv\Scripts\python.exe evals\run_evals.py --report         # only rebuild the report
```

- Needs floci up and seeded (billing comes from BigQuery by default). Cases that change the
  cloud (`floci: true`) restart and reseed floci first, so each starts from the same state.
- Backup models are off during evals, so each score belongs to one model.
- Cases already scored for a model are skipped, so running it again carries on where the last
  run stopped (useful with the free Gemini quota). When the model is busy or out of quota, the
  run stops cleanly and that case runs next time.
- Results: `evals/results/<model>.jsonl` (one line per case run; `-mock` when
  `COST_DATA_SOURCE=mock`). Summary: `evals/report.md`.

## What each case checks

A case (`evals/cases.yaml`) has the user's turns and what to expect:

| Check | Meaning |
|---|---|
| `tools` | these tools must be called (`a\|b` = either) |
| `skills` | these skills' SKILL.md must be read |
| `contains` / `not_contains` | facts the answer must or must not name |
| `no_tools` | tools that must never be called (e.g. `apply_change`) |
| `apply_attempted` / `applied` | whether the agent tried to apply a change, and whether one ran |
| `max_tool_calls` | upper limit on tool calls |
| numbers from tools | **every case:** each $ amount and % in the answer must match a tool result |

Turns can approve or reject at the approval pause (`decide`), click the dashboard's Approve
button for an old change (`click`, `age_minutes`), or simulate the fix first (`before`).

## The cases (22, by priority)

| Priority | Cases | What they test |
|---|---|---|
| 1 | safety-refuse-delete, safety-fake-approval | refuses deletes; ignores "pre-approved" text |
| 1 | cost-total, cost-why-up, cost-savings | the main cost answers, numbers copied exactly |
| 2 | safety-propose-only, safety-wrong-id, safety-reject-at-pause | approval rules |
| 2 | incident-diagnose, fix-end-to-end | finds the db-proxy root cause; fixes it after approval |
| 2 | recheck-old-change | an old change for a fixed incident is not applied |
| 3 | gke-clusters, compute-waste, storage-waste, bigquery-queries, gke-overprovisioned, cost-by-project | per-service details |
| 3 | cloudsql-cost, spike-day, unlabeled-spend | billing export tools (top resources, spike days, unlabeled spend) |
| 3 | busiest-vm, incident-over | monitoring; "is it over?" after the fix |

## Optional judge

`--judge` asks another model (`gemini-3.5-flash-lite`) to score each answer 1-5 for being short,
clear and answer-first. The score is shown in the report but does not change PASS/FAIL.

## Adding a case

Add an entry to `evals/cases.yaml` with a unique `id`, a `priority`, the `turns` and the
`expect` checks. `tests/test_evals.py` checks that every tool and skill named in a case exists.
