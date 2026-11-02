# Architecture

## The pieces

```text
            ┌──────────────────────────┐      ┌──────────────────────────────────┐
 you ──────►│ chat.py (terminal)       │      │ dashboard/app.py (FastAPI :8060) │
            │ y/n approval prompt      │      │ Chat page + Approve/Reject       │
            └────────────┬─────────────┘      └───────────────┬──────────────────┘
                         └──────────────┬─────────────────────┘
                                        ▼
            ┌────────────────────────────────────────────────────────────────┐
            │ agent.py — one Deep Agent (deepagents 0.7, LangGraph)          │
            │  • model: Gemini, with backup models (ModelFallbackMiddleware) │
            │  • rules: SYSTEM_PROMPT                                        │
            │  • skills: skills/ mounted read-only at /skills/               │
            │  • approval: interrupt_on={"apply_change"} pauses the run      │
            │  • memory: LangGraph checkpointer (SQLite for saved chats)     │
            │  • no shell, no file writes, no subagents                      │
            └────────────────────────────┬───────────────────────────────────┘
                                         │ MCP over stdio (one session per chat)
                                         ▼
            ┌────────────────────────────────────────────────────────────────┐
            │ sre_mcp/ — MCP server "gcp-sre-mcp", 32 tools                   │
            │  cost/           20 tools ── data source:                      │
            │                    bigquery: SQL on the billing export table   │
            │                    mock:     sample JSON files                 │
            │  observability/   7 tools ── Monitoring + Logging REST APIs    │
            │  changes/         5 tools ── Compute + Storage REST APIs,      │
            │                              history in data/changes.jsonl     │
            └────────────────────────────┬───────────────────────────────────┘
                                         ▼
            ┌────────────────────────────────────────────────────────────────┐
            │ floci-gcp emulator (docker-compose.yml, localhost:4588)        │
            │  BigQuery (+ floci-duck SQL engine), Compute, Storage,         │
            │  Monitoring, Logging. Filled by seed/.                          │
            └────────────────────────────────────────────────────────────────┘
```

## How one question flows

1. You ask a question (terminal or dashboard). The agent sees the rules and a one-line
   description of each skill.
2. It reads the full `SKILL.md` it needs with `read_file` (progressive disclosure: skills
   cost no tokens until used).
3. It calls tools on the MCP server. Each tool returns JSON with the numbers; the agent must
   copy them, never calculate its own.
4. It answers. Each step is saved by the checkpointer, so a chat can continue later.

## How a change is made

1. The agent calls `propose_change` (changes nothing). The server checks the action is
   allowed, reads the resource, and saves a plan with a change ID (`chg-xxxxxx`).
2. The agent shows the plan and asks "Approve chg-xxxxxx?". It stops.
3. You say yes. The agent calls `apply_change`; LangGraph **pauses** before it runs.
4. You approve again (terminal y/n, or the dashboard button). The server re-reads the
   resource and refuses if it changed since the proposal; otherwise it applies the change
   and writes "CHANGE APPLIED" to Cloud Logging.
5. The agent checks the result, for example with `check_incident_status`.

A change that is waiting can be approved or cancelled later from the dashboard's Changes
page ("Open chat"). If it is older than 10 minutes, the agent re-checks it first.

## Billing data

The cost tools read through one interface (`sre_mcp/cost/data/base.py`). Two sources:

| Source | `COST_DATA_SOURCE` | Where |
|---|---|---|
| BigQuery billing export (default) | `bigquery` | `bigquery_source.py`: read-only SQL on a detailed (resource-level) Cloud Billing export table |
| Mock files | `mock` | `mock_source.py`: `sre_mcp/cost/data/mock/*.json` |

Costs (per month, service, project, GKE workload, VM, disk, IP, bucket and SKU) come from the
export. What billing cannot know (CPU and memory use, GKE requests, bucket sizes, query
details) still comes from the mock files; on real GCP it would come from Cloud Monitoring,
the inventory APIs and `INFORMATION_SCHEMA.JOBS`.

The sample table (`seed/seed_billing.py`) has the same totals as the mock files, so both
sources give identical answers (`tests/test_bigquery_billing.py` checks this, including a live
run on floci). Planted for the demo: a GKE cost increase (payments-api, web-staging), a
BigQuery spike day (2026-09-17), and unlabeled spend (legacy-ftp, old snapshots, unused IPs).

## The sample incident

`seed/seed_floci.py` writes 24 hours of metrics and logs. In the last 3 hours db-proxy's CPU
is above 90%, its connection pool is exhausted, and payments-api times out connecting to it.
A search-indexer error is an unrelated distraction. Restarting db-proxy (the approved fix)
writes simulated recovery data (`seed/simulate_fix.py`), because floci runs no real workload.
`check_incident_status` then says "resolved", even though the old errors stay in the logs.

## Storage

No database server. Local files (git-ignored):

| File | Holds |
|---|---|
| `chat_history.sqlite` | Every dashboard chat, step by step (LangGraph `AsyncSqliteSaver`) |
| `chat_links.json` | Which chat proposed which change |
| `data/changes.jsonl` | Every proposed, applied and cancelled change |
| `mcp_server.log` | The MCP server's own log |

For a shared multi-user version, swap SQLite for Postgres (`langgraph-checkpoint-postgres`).
