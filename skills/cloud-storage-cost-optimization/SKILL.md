---
name: cloud-storage-cost-optimization
metadata:
  version: "1.0.0"
  category: FinOps
  publisher: custom
description: >-
  Analyze and reduce Google Cloud Storage (GCS bucket) costs: cost per bucket,
  storage versus operations versus egress, cold data kept in an expensive
  storage class, old object versions, data that can be deleted, missing
  lifecycle rules, and high network egress. Use when the user asks why Cloud
  Storage costs are high, which buckets cost the most, whether to change
  storage classes, or how to save on storage. Don't use for VM disks or
  snapshots (use compute-engine-cost-optimization), BigQuery storage (use
  bigquery-slot-cost-optimizer), or overall bill questions (use
  billing-financial-metrics first).
---

# Cloud Storage Cost Optimization

This skill provides guidance on finding and explaining Cloud Storage savings,
using per-bucket cost, size and access patterns as evidence.

## Overview

When users ask about storage costs (e.g., "Which buckets cost the most?",
"Are we using the right storage classes?", "How can we save on Cloud
Storage?"), use this skill to give a structured, number-backed answer. Work in
this order: delete what is not needed, then move what is kept but rarely read
to a cheaper class, then automate both with lifecycle rules.

## Instructions

When handling a Cloud Storage question:

1.  **Get the Numbers from Tools**: Call the Cloud Storage tools. Copy figures
    exactly as returned. Never invent, add up, or recalculate numbers. If data
    is missing, say so.
2.  **Provide a Direct Answer**: Start with the answer to the question, then
    the supporting metrics.
3.  **Show Where the Money Goes**: Call `get_storage_cost_by_bucket` for the
    total, the top buckets, and the split between storage (data at rest),
    operations (reads, writes, lists) and egress (data sent out).
4.  **Find the Waste**: Call `get_storage_waste`.
    -   **Cleanups**: Old object versions (kept by versioning) and data the
        owner marked deletable, such as expired temp files. Recommend a
        lifecycle rule that deletes them automatically, after the owner
        confirms what must be kept.
    -   **Class changes**: Cold data kept in Standard. Explain the classes:
        Nearline (read about once a month, 30-day minimum), Coldline (about
        once a quarter, 90-day minimum), Archive (about once a year, 365-day
        minimum). Colder classes cost less to store but more to read, and data
        deleted early is still billed for the minimum time. Recommend a
        lifecycle rule that changes the class by age. For buckets with mixed
        or unknown access, recommend Autoclass, which moves objects
        automatically.
    -   **No lifecycle rules**: List these buckets. Rules make the savings
        permanent instead of a one-off clean-up.
    -   **High egress**: Flag it. Suggest Cloud CDN for public content, or
        keeping readers in the same region as the bucket. The tools do not
        estimate this saving; say so.
5.  **Estimate Savings**: Always label savings as estimates and state the
    assumptions returned by the tools. Show the saving as a dollar amount per
    month and as a percent of the Cloud Storage cost.
6.  **Recommend, Never Change**: Present fixes as recommendations for a human
    to approve.

## Key Points & Metrics

-   **Currency and Period**: Costs are USD per calendar month unless stated.
-   **Cost Parts**: Bucket cost = storage + operations + egress. Class changes
    only lower storage.
-   **Cold Data**: Share of a bucket's data not read for 30+ days, and how long
    since it was last read. This decides the target class.
-   **Retrieval Risk**: Backups and archives that must be restored fast may
    need a warmer class than the cheapest one. Say so.
-   **No Double Counting**: Data that is deleted is not also counted as moved.
-   **Defaults**: Assume the latest month, all projects, and ordering by cost
    descending, unless specified otherwise.

## Available Tools

| Question | Tool |
|---|---|
| Cost per bucket (storage, operations, egress) | `get_storage_cost_by_bucket` |
| Class changes, cleanups, missing lifecycle rules, high egress | `get_storage_waste` |
| Ranked savings across all services | `estimate_savings` |

## Read-Only Rule

This skill only analyzes and recommends. It must not delete objects, change
storage classes, or create or edit buckets or lifecycle rules. Describe such
actions as recommendations that need explicit human approval.

## Related Skills

-   **`billing-financial-metrics`**: Overall bill, month comparison, and cost
    by service.
-   **`compute-engine-cost-optimization`**: VM disks and snapshots (these are
    Compute Engine, not Cloud Storage).
-   **`google-cloud-waf-cost-optimization`**: General FinOps guidance.
