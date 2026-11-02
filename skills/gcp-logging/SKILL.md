---
name: gcp-logging
metadata:
  version: "1.0.0"
  category: Observability
  publisher: custom
description: >-
  Search and summarize Google Cloud Logging entries for VMs and GKE
  containers: recent errors grouped by message, error counts per resource,
  text search, and short incident summaries. Use when the user asks about
  errors, failures, crashes, timeouts, what is going wrong, what a service
  logged, or wants an incident summary. Don't use for CPU or memory usage
  (use gcp-monitoring), or for cost questions (use billing-financial-metrics
  and the service cost skills).
---

# GCP Logging

This skill provides guidance on answering error and incident questions with
Cloud Logging entries as evidence.

## Overview

When users ask about errors or incidents (e.g., "Any errors in the last
hour?", "Why is payments-api failing?", "What happened to db-proxy?",
"Summarize today's incident"), use this skill to find the main errors, which
resource they come from, and when they started. Start with a summary, then
search for detail.

## Instructions

1.  **Get the Facts from Tools**: Copy counts, messages and times exactly as
    returned. Never invent or recount entries. If a tool returns nothing,
    say so.
2.  **Start with the Big Picture**: Call `get_recent_errors` (errors grouped
    by message, most frequent first) or `get_log_summary` (counts per
    severity and per resource) for the time window (`hours`, default 24).
3.  **Zoom In**: Call `search_logs` with `query` (text in the message),
    `resource` (VM, cluster, namespace or container name) and/or `severity`
    (minimum, e.g. `WARNING`) to see individual entries and exact times.
4.  **Find the Root Cause, Not Just the Loudest Error**: The most frequent
    error is often a symptom. Look for the earliest error in the window and
    for errors that name another service (e.g., "timeout connecting to
    db-proxy" points at db-proxy). Check that other resource's logs too.
5.  **Link to Metrics**: If an error names a resource, check `gcp-monitoring`
    (`get_resource_utilization`, `get_metric_timeseries`) for a spike at the
    same time. Say whether the timing matches.
6.  **Check if It Is Over**: Call `check_incident_status` for the root
    resource (e.g. `db-proxy`). It compares the last error time with the
    latest CPU in code and returns a verdict: `ongoing`, `recovering`,
    `resolved` or `no_errors`. Trust the verdict: old errors stay in the logs
    after a fix, which does not mean it is still happening.
7.  **Changes Need Approval**: Recommend actions for a human to approve. If
    the user wants one done and it is an allowed action (restart_vm, resize_vm), use
    `propose_change`, show the plan, and call `apply_change` only after the
    user approves that change ID (see the agent's change rules). Never delete anything.

## Severity Levels

DEFAULT < DEBUG < INFO < NOTICE < WARNING < ERROR < CRITICAL < ALERT <
EMERGENCY. "Errors" means ERROR and above. Treat CRITICAL and above as most
urgent, even if rare.

## Incident Summary Format

- **What happened** in one line.
- **Impact**: which service and how many errors (from the tools).
- **Timeline**: first seen and last seen (still happening?).
- **Likely root cause**, with the evidence (log lines and metrics).
- **Recommended next steps** for a human to approve.
- **Not checked**: anything the tools could not show.

## Data Note

In this prototype the logs come from the local floci-gcp emulator with sample
data, not real traffic. Say so if the user may think it is live.
