# Demo guide (about 15 minutes)

## Before the demo (5 minutes, no AI quota)

```powershell
docker compose up -d
.venv\Scripts\python.exe -m seed.seed_floci
.venv\Scripts\python.exe -m seed.seed_billing
.venv\Scripts\python.exe check.py                 # all lines should say OK
.venv\Scripts\python.exe dashboard\app.py         # http://127.0.0.1:8060
```

Seed on the day of the demo: metrics and logs are relative to "now". Ask one billing question
before the audience arrives, so floci's SQL engine is already started.

The free Gemini tier allows only a few questions per model per day. Rehearse on a different
day, or set a paid key.

## 1. What it is (1 minute)

Show the Overview page. One AI agent, 32 tools from our own MCP server, 10 skills, running on a
local copy of Google Cloud with a sample company and a planted incident.

## 2. Costs (4 minutes) — Chat page

1. **"Why did our GCP bill go up last month?"**
   Expect: $12,450, up $965 (8.4%); Kubernetes Engine +$600 and BigQuery +$350. Point out the
   numbers come from SQL on a BigQuery table in the real billing export format.
2. **"Was there a spike day?"** → 2026-09-17, BigQuery analytics, about 6x a normal day.
3. **"Where can we save money? Top 3."** → savings table plus a JSON block (cost-report skill).
4. **"How much spend has no team label?"** → $200: legacy-ftp, old snapshots, unused IPs.

## 3. The incident (5 minutes)

1. **"Payments are failing. What is wrong?"**
   Expect: db-proxy's connection pool is exhausted and CPU is above 90%, so payments-api times
   out. It explains a fix in words but proposes nothing yet.
2. **"Fix it."** → it proposes `restart_vm db-proxy` and asks "Approve chg-...?".
3. **"yes"** → an Approve/Reject card appears (the code-level lock). Click **Approve**.
4. **"Is it fixed now?"** → `check_incident_status` says "resolved". Note: the restart writes
   simulated recovery data, because the emulator runs no real workload.

## 4. Safety (2 minutes)

- **"Delete legacy-ftp."** → refused: deletes do not exist.
- Changes page: every change with its status. A waiting change has **Open chat**, to approve or
  cancel it later. The agent re-checks old changes before applying them.

## 5. Quality (2 minutes)

Show `evals/report.md`: questions with known answers, scored automatically per model. Every
$ and % in an answer must come from a tool result, or the case fails.

## If something goes wrong

| Symptom | Do this |
|---|---|
| "Gemini busy" | Wait a minute; the agent also switches to backup models by itself |
| Tools say floci is not reachable | `docker compose up -d`, then seed again |
| First billing answer is slow | floci is starting its SQL engine; ask again |
| Incident already shows "resolved" before the fix | Seed again (`seed_floci`) |
