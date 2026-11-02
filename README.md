# GCP SRE Agent (LangChain Deep Agents + Gemini)

An AI assistant for Google Cloud. It explains your bill, finds savings, checks how busy
resources are, finds the root cause of errors, and fixes problems **only after a human
approves**. It can never delete anything.

It runs fully on your laptop against **floci**, a local Google Cloud emulator, filled with a
sample company: billing data, VMs, buckets, metrics, logs, and a planted incident. Nothing
touches real GCP.

```text
you ── terminal chat (chat.py) or web dashboard with chat (dashboard/, port 8060)
         │
         ▼
  agent.py  one Deep Agent (Gemini). Rules + approval pause before any change.
         │   reads skills/ (10 SKILL.md "how to think" guides, read-only)
         ▼
  sre_mcp/  MCP server "gcp-sre-mcp", 32 tools (the "facts and actions")
         │   cost (20)  ── SQL on the Cloud Billing export in BigQuery
         │   monitoring + logging (7) ── Cloud Monitoring / Cloud Logging APIs
         │   changes (5) ── propose, apply (after approval), cancel, history
         ▼
  floci-gcp emulator (Docker, localhost:4588) ── later: real GCP
```

More detail: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Demo script:
[docs/DEMO_GUIDE.md](docs/DEMO_GUIDE.md). Evals: [docs/EVALS.md](docs/EVALS.md).

## Quick start

You need **Python 3.12+**, **Docker Desktop** and a **Gemini API key** (free tier works:
https://aistudio.google.com/apikey).

```powershell
# 1. Python environment (Windows; on macOS/Linux use .venv/bin/python)
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt

# 2. Settings: copy the example and put your Gemini key in .env
copy .env.example .env

# 3. Start the fake Google Cloud and fill it with the sample company
docker compose up -d
.venv\Scripts\python.exe -m seed.seed_floci      # VMs, buckets, metrics, logs, the incident
.venv\Scripts\python.exe -m seed.seed_billing    # the billing export table in BigQuery

# 4. Check that everything is ready (no AI quota used)
.venv\Scripts\python.exe check.py
.venv\Scripts\python.exe -m pytest -q            # 105 tests, no key needed

# 5. Talk to the agent
.venv\Scripts\python.exe chat.py                  # terminal; type "exit" to quit
.venv\Scripts\python.exe dashboard\app.py         # web: http://127.0.0.1:8060 (Chat page)
```

Run the two seed commands again after floci restarts or on a new day: the sample
metrics and logs are relative to "now".

**Try asking:**

- "Why did our GCP bill go up last month?"
- "Where can we save money? Give me the top 3."
- "Was there a cost spike day in September?" / "How much spend has no team label?"
- "Payments are failing. What is wrong?" → "Fix it." → approve → "Is it fixed now?"
- "Delete legacy-ftp." (refused: no deletes)

## What is in this folder

| Path | What it is |
|---|---|
| `agent.py` | The agent: model and backup models, rules (system prompt), MCP tools, read-only skills, approval pause |
| `chat.py` | Terminal chat with y/n approval and retries when Gemini is busy |
| `check.py` | Checks Python, packages, key, floci, sample data, billing table, tools and skills |
| `sre_mcp/` | MCP server `gcp-sre-mcp` (32 tools). Run alone with `python -m sre_mcp` for any MCP app |
| `sre_mcp/cost/` | Cost tools and data sources: BigQuery billing export, or mock JSON files |
| `sre_mcp/observability/` | Monitoring, logging and incident-status tools |
| `sre_mcp/changes/` | Approved changes: inventory, propose, apply, cancel, history |
| `skills/` | 10 skills (SKILL.md), mounted read-only at `/skills/` |
| `seed/` | Fills floci: `seed_floci` (cloud), `seed_billing` (billing export), `simulate_fix` |
| `dashboard/` | Web dashboard (FastAPI + plain HTML/JS) with a Chat page and Approve/Reject buttons |
| `evals/` | 22 questions with known answers, scored automatically |
| `tests/` | 105 tests that need no AI key (the live BigQuery test runs only when floci is up) |
| `docker-compose.yml` | The floci emulator |
| `.claude/skills/deepagents-new-agent/` | Claude Code skill that creates a new Deep Agents project like this one |

Local run data (git-ignored): `data/changes.jsonl` (change history), `chat_history.sqlite`
(saved chats), `chat_links.json` (which chat proposed which change), `mcp_server.log`.

## The tools (32)

| Area | Tools |
|---|---|
| Billing | get_cost_summary, get_cost_by_service, get_cost_by_project, compare_months, get_daily_costs, get_daily_spikes, get_top_resources, get_unlabeled_spend, run_billing_query (read-only SQL) |
| GKE | get_gke_cost_by_cluster, get_gke_cost_by_namespace, get_gke_top_workloads, get_gke_overprovisioned_workloads |
| BigQuery | get_bigquery_expensive_queries |
| Compute Engine | get_compute_cost_by_instance, get_compute_waste, get_compute_commitment_coverage |
| Cloud Storage | get_storage_cost_by_bucket, get_storage_waste |
| Savings | estimate_savings |
| Monitoring | list_metrics, get_metric_timeseries, get_resource_utilization |
| Logging | search_logs, get_recent_errors, get_log_summary, check_incident_status |
| Changes | get_inventory, propose_change, apply_change, cancel_change, list_changes |

**Where cost data comes from.** All costs come from a Cloud Billing **detailed
(resource-level) export** table in BigQuery: `billing_export.gcp_billing_export_resource_v1_...`
in floci, with daily rows for Aug and Sep 2026. Things billing cannot know (CPU and memory use,
GKE requests, bucket sizes, query details) come from sample files for now; later from Cloud
Monitoring, the inventory APIs and `INFORMATION_SCHEMA.JOBS`. To use the mock files only, set
`COST_DATA_SOURCE=mock` (no BigQuery needed).

**Moving to real GCP billing** is a settings change: `BQ_BILLING_TABLE=<project.dataset.table>`,
`BQ_API_URL=https://bigquery.googleapis.com` and a read-only `GCP_ACCESS_TOKEN`.

## The skills (10)

billing-financial-metrics, gke-cost-analysis, gke-cost-optimization,
bigquery-slot-cost-optimizer, compute-engine-cost-optimization, cloud-storage-cost-optimization,
google-cloud-waf-cost-optimization, gcp-monitoring, gcp-logging, and **cost-report** (the
format of a savings report: short table plus a JSON block).

## Safety

- **Two locks on changes.** The agent's rules: it proposes a change, asks "Approve chg-...?",
  and applies only that ID after you say yes. And the code: `apply_change` pauses the agent
  (LangGraph `interrupt_on`) until you answer y/n or click Approve/Reject.
- **Only safe actions exist:** resize, stop, start or restart a VM; change a bucket's storage
  class; add a lifecycle rule. There is no delete. A change is refused if the resource changed
  since it was proposed.
- **No file writes, no shell, no subagents.** The agent's file tools can only read skills.
- **Local only.** Changes only run against the floci emulator. Billing SQL is read-only
  (one SELECT; write statements are refused).
- **Keys:** only in `.env`, which is git-ignored.

## Models and Gemini limits

Main model `gemini-3.5-flash`. If it is busy (503) or out of quota (429), the agent switches by
itself to `gemini-3.8-flash`, then `gemini-3.5-flash-lite`. The free tier has a small daily
quota per model: a few questions can use most of it. Change models with `GEMINI_MODEL` and
`GEMINI_FALLBACKS` in `.env`.

## Troubleshooting

| Problem | Fix |
|---|---|
| "Cannot reach http://localhost:4588" | Start Docker Desktop, then `docker compose up -d` |
| `check.py`: billing table missing / no VMs | Run both seed commands again (floci keeps data in memory) |
| First billing question is slow or says the SQL engine is not healthy | floci starts its SQL engine (`floci-duck`) on the first query; ask again |
| "Gemini busy" / 429 | Wait, or set other models in `.env`; the free quota resets daily |
| Seeding says "must be more recent" | `docker compose restart`, then seed again |
| Port 8060 in use | Set `DASHBOARD_PORT=8061` in `.env` |
| Container name `floci-gcp` already in use | Another copy of floci is running: `docker rm -f floci-gcp`, then `docker compose up -d` |

floci needs access to the Docker socket (see `docker-compose.yml`) to start its BigQuery SQL
engine as a second container. Only use this on your own machine.

## Other versions of this agent

| | ADK (`gcp-cost-optimizer`) | Claude Desktop (`claude-desktop-agent`) | Deep Agents (this) |
|---|---|---|---|
| Agent code | Python (ADK) | none | Python (`agent.py`) |
| Model | Gemini | Claude | Gemini, with backup models |
| Tools | 15 cost tools, in-process | MCP server (26 tools) | own MCP server (32 tools) |
| Billing data | mock JSON | mock JSON | BigQuery billing export (SQL) |
| Approval pause | none | Claude Desktop "ask" permission | LangGraph interrupt (terminal y/n, dashboard buttons) |
| UI | ADK web | Claude Desktop + dashboard | terminal, or dashboard with chat |
