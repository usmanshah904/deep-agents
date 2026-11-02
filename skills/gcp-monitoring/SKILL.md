---
name: gcp-monitoring
metadata:
  version: "1.0.0"
  category: Observability
  publisher: custom
description: >-
  Read Google Cloud Monitoring metrics for VMs and GKE containers: CPU and
  memory usage over time, high (saturated) and idle resources, spikes, and how
  usage links to cost. Use when the user asks which VMs or workloads are busy,
  overloaded or idle, what CPU or memory looked like over time, what metrics
  exist, or whether a resource is the cause of slowness. Don't use for log
  messages or errors (use gcp-logging), or for cost totals (use
  billing-financial-metrics and the service cost skills).
---

# GCP Monitoring

This skill provides guidance on answering usage and health questions with
Cloud Monitoring metrics as evidence.

## Overview

When users ask about resource usage (e.g., "Which VM has high CPU?", "Is
anything idle?", "What did db-proxy CPU look like today?", "Why is checkout
slow?"), use this skill to give a short, number-backed answer. Start broad
(all resources), then zoom into the one that stands out.

## Instructions

1.  **Get the Numbers from Tools**: Copy figures exactly as returned. Never
    invent, average or recalculate numbers. If a tool returns no data, say so.
2.  **Start Broad**: Call `get_resource_utilization` with `kind` = `vm` or
    `gke` and `metric` = `cpu` or `memory`. It returns average, peak and
    latest usage in %, plus a `flag` (`high`, `idle` or `normal`) and counts.
3.  **Zoom In**: For a flagged resource, call `get_metric_timeseries` with the
    `metric_type` from step 2 and the resource name, to see when it started
    and whether it is still happening (compare early points with the latest).
4.  **Unknown Metric**: If unsure what exists, call `list_metrics` first.
5.  **Link to Logs**: For a `high` resource, check `gcp-logging`
    (`get_recent_errors` with the resource name) to see if errors match the
    same time window. Say clearly whether the timing matches.
6.  **Link to Cost**: For an `idle` resource or a workload using far less than
    it requests, mention the matching cost tool (`get_compute_waste`,
    `get_gke_overprovisioned_workloads`) for the dollar impact.
7.  **Changes Need Approval**: Recommend actions for a human to approve. If
    the user wants one done and it is an allowed action (resize_vm, restart_vm), use
    `propose_change`, show the plan, and call `apply_change` only after the
    user approves that change ID (see the agent's change rules). Never delete anything.

## Reading the Metrics

| Metric (kind, metric) | Meaning |
|---|---|
| vm, cpu | VM CPU use as % of its vCPUs |
| vm, memory | VM memory use % (needs the Ops Agent on real GCP) |
| gke, cpu | Container CPU use as % of its CPU **request** |
| gke, memory | Container memory use as % of its memory **request** |

- **High** = peak at or above 80%. Can mean saturation: slow responses,
  timeouts, throttling. For GKE, above 100% means the container uses more
  than it requested.
- **Idle** = average below 5%. Likely waste.
- A **spike** (latest far above average) is more urgent than a steady high.

## Report Format

- **Answer** in one line (e.g., "db-proxy is the only VM with high CPU").
- **Evidence**: a small table with resource, average, peak, latest, flag.
- **When**: the time it started, from the time series, if checked.
- **Likely cause and next step**, marked as a recommendation.
- **Limits**: say what was not checked (for example, memory on VMs).

## Data Note

In this prototype the metrics come from the local floci-gcp emulator with
sample data, not real traffic. Say so if the user may think it is live.
