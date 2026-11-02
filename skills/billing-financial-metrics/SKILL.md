---
name: billing-financial-metrics
metadata:
  version: "1.0.0"
  category: FinOps
  publisher: custom
description: >-
  Answer natural language questions about overall Google Cloud spend and track
  financial metrics: total monthly cost, change versus the previous month, cost
  by service and project, major cost drivers, and estimated savings. Use when
  the user asks why the GCP bill increased, which services cost the most, what
  changed compared with last month, how much could be saved, or wants a cost
  summary. Don't use for GKE namespace or workload cost deep dives (use
  gke-cost-analysis), applying GKE optimizations (use gke-cost-optimization),
  BigQuery query or slot analysis (use bigquery-slot-cost-optimizer), VM
  analysis (use compute-engine-cost-optimization), bucket analysis (use
  cloud-storage-cost-optimization), or general FinOps best practices (use
  google-cloud-waf-cost-optimization).
---

# Billing and Financial Metrics

This skill provides guidance on answering natural language questions about
overall GCP spend, using financial metrics as evidence.

## Overview

When users ask about the bill (e.g., "Why did our GCP bill increase?", "Which
services cost the most?", "What changed compared with last month?", "How much
could we save?"), use this skill to give a structured, number-backed answer.
It is the first step for most cost questions. It finds where the money goes,
then hands off to the service skills for details.

## Instructions

When handling a financial question:

1.  **Get the Numbers from Tools**: Call the billing tools. Copy figures
    exactly as returned. Never invent, add up, or recalculate numbers. If data
    is missing, say so.
2.  **Provide a Direct Answer**: Start with the answer to the question, then
    the supporting metrics.
3.  **Report the Core Metrics**: Total monthly cost, previous-month cost,
    change in amount and percent, and cost by service (largest first).
4.  **Identify the Cost Drivers**: Use the month comparison to find which
    services increased the most. Report each as amount and percent.
5.  **Drill Down with the Matching Skill**: If a driver is GKE, load
    **`gke-cost-analysis`**. If BigQuery, load
    **`bigquery-slot-cost-optimizer`**. If Compute Engine, load
    **`compute-engine-cost-optimization`**. If Cloud Storage, load
    **`cloud-storage-cost-optimization`**. For other services, use
    **`google-cloud-waf-cost-optimization`** for general guidance.
6.  **Estimate Savings**: Call the savings tool for ranked opportunities.
    Always label savings as estimates and state the assumptions. Show the
    saving as a dollar amount per month and as a percent of that service and of
    the total bill.
7.  **Recommend, Never Change**: Present fixes as recommendations for a human
    to approve.

## Key Points & Metrics

-   **Currency and Period**: Costs are USD per calendar month unless stated.
-   **Month-over-Month Change**: `(current - previous) / previous`, shown with
    one decimal place. If the previous month is missing, say no comparison is
    possible.
-   **Cost Share**: Each service's share of the total bill, to show where the
    money goes.
-   **Savings Percent**: Report both percent of the service cost and percent of
    the total bill.
-   **Data Coverage**: Detailed data may exist only for some services. State
    which services are covered and which are not.
-   **Defaults**: Assume the latest month versus the previous month, ordering
    by cost descending, unless specified otherwise.

## Available Tools

| Question | Tool |
|---|---|
| Total cost and change vs last month | `get_cost_summary` |
| Cost by service | `get_cost_by_service` |
| Cost by project | `get_cost_by_project` |
| What changed vs last month | `compare_months` |
| Ranked savings opportunities | `estimate_savings` |

## Read-Only Rule

This skill only analyzes and recommends. It must not change billing settings,
resize or delete resources, or purchase commitments (CUDs). Describe such
actions as recommendations that need explicit human approval.

## Related Skills

-   **`gke-cost-analysis`**: GKE cost by cluster, namespace, and workload.
-   **`gke-cost-optimization`**: GKE rightsizing, Spot VMs, quotas.
-   **`bigquery-slot-cost-optimizer`**: Expensive BigQuery queries and slots.
-   **`compute-engine-cost-optimization`**: Idle and oversized VMs, unused
    disks and IPs, CUDs and Spot VMs.
-   **`cloud-storage-cost-optimization`**: Storage classes, old object
    versions, lifecycle rules and egress for buckets.
-   **`google-cloud-waf-cost-optimization`**: General FinOps and discount
    guidance for any service.

## Report Template

A suggested answer layout is in
[references/report-template.md](references/report-template.md).
