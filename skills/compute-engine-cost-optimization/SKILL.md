---
name: compute-engine-cost-optimization
metadata:
  version: "1.0.0"
  category: FinOps
  publisher: custom
description: >-
  Analyze and reduce Google Compute Engine (VM) costs: cost per VM, idle VMs,
  oversized VMs, unused disks, snapshots and static IPs, committed use
  discount (CUD) coverage, and Spot VMs for batch work. Use when the user asks
  why Compute Engine costs are high, which VMs cost the most, which VMs are
  idle or oversized, whether to buy commitments, or how to save on VMs. Don't
  use for GKE nodes or workloads (use gke-cost-analysis and
  gke-cost-optimization), overall bill questions (use
  billing-financial-metrics first), or BigQuery (use
  bigquery-slot-cost-optimizer).
---

# Compute Engine Cost Optimization

This skill provides guidance on finding and explaining Compute Engine (VM)
savings, using per-VM cost and usage as evidence.

## Overview

When users ask about VM costs (e.g., "Which VMs cost the most?", "Do we have
idle VMs?", "Should we buy commitments?", "How can we save on Compute
Engine?"), use this skill to give a structured, number-backed answer. Work in
this order, because each step changes the size of the next one: remove waste,
then rightsize, then pick the right pricing model (Spot or CUD).

## Instructions

When handling a Compute Engine question:

1.  **Get the Numbers from Tools**: Call the Compute Engine tools. Copy
    figures exactly as returned. Never invent, add up, or recalculate numbers.
    If data is missing, say so.
2.  **Provide a Direct Answer**: Start with the answer to the question, then
    the supporting metrics.
3.  **Show Where the Money Goes**: Call `get_compute_cost_by_instance` for the
    total Compute Engine cost, the top VMs, and the cost of unused resources.
4.  **Find the Waste First**: Call `get_compute_waste`.
    -   **Idle VMs**: Recommend confirming with the owner, taking a snapshot,
        then stopping or deleting.
    -   **Unused disks, snapshots and IPs**: Recommend deleting after a backup
        check. Unattached disks and reserved IPs are billed even when no VM uses
        them.
    -   **Oversized VMs**: Recommend a smaller machine type, or a custom machine
        type when only CPU or only memory is too big. Mention that Google's
        rightsizing recommendations (Recommender) can confirm the target size.
5.  **Then Pick the Pricing Model**: Call `get_compute_commitment_coverage`.
    -   **Batch VMs**: Recommend Spot VMs. They can be stopped at any time, so
        only fault-tolerant work that can retry should use them.
    -   **Steady production VMs**: Recommend a 1-year committed use discount
        (CUD) for the rightsized size. Never commit to an oversized VM.
    -   **Sustained use discounts (SUDs)**: Applied automatically to N1 and N2
        VMs that run most of the month. They are already in the cost. A CUD
        replaces the SUD, so the extra saving is smaller than the list discount.
6.  **Non-Production VMs**: Recommend shutting staging and dev VMs down
    outside working hours (instance schedules) instead of buying commitments.
    Say this is general advice; the tools do not estimate this saving.
7.  **Estimate Savings**: Always label savings as estimates and state the
    assumptions returned by the tools. Show the saving as a dollar amount per
    month and as a percent of the Compute Engine cost.
8.  **Recommend, Never Change**: Present fixes as recommendations for a human
    to approve.

## Key Points & Metrics

-   **Currency and Period**: Costs are USD per calendar month unless stated.
-   **Utilization**: Average CPU and memory use over the month. A VM is sized
    by its higher value, because both must fit.
-   **Commitment Coverage**: Share of steady production VM cost already covered
    by CUDs.
-   **Order Matters**: Savings from waste, rightsizing, and Spot or CUD are
    calculated in that order, so they do not double count.
-   **Risk**: Deleting resources cannot be undone. Spot VMs can be stopped at
    any time. CUDs are a 1- or 3-year payment that cannot be cancelled. Say so.
-   **Defaults**: Assume the latest month, all projects, and ordering by cost
    descending, unless specified otherwise.

## Available Tools

| Question | Tool |
|---|---|
| Cost per VM and unused resources | `get_compute_cost_by_instance` |
| Idle VMs, oversized VMs, unused disks, snapshots and IPs | `get_compute_waste` |
| CUD coverage and Spot candidates | `get_compute_commitment_coverage` |
| Ranked savings across all services | `estimate_savings` |

## Read-Only Rule

This skill only analyzes and recommends. It must not stop, delete, resize or
create VMs, disks, snapshots or IPs, and must not purchase commitments (CUDs).
Describe such actions as recommendations that need explicit human approval.

## Related Skills

-   **`billing-financial-metrics`**: Overall bill, month comparison, and cost
    by service.
-   **`gke-cost-optimization`**: GKE node and workload savings. GKE nodes are
    VMs, but use the GKE skills for them.
-   **`google-cloud-waf-cost-optimization`**: General FinOps and discount
    guidance.
