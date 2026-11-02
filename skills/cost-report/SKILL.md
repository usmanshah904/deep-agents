---
name: cost-report
description: The required format for cost-saving findings and the savings report (a short table plus a JSON block). Use whenever you list savings opportunities or answer "where can we save".
---

# Cost report format

Use this layout for any list of savings. It keeps answers the same every time, and the JSON
block lets other apps (dashboard, tickets) read the report.

## Layout

1. One line: the total estimated monthly saving **as returned by `estimate_savings`**
   (`total_estimated_monthly_saving`), how many findings you list, and the month of the data.
2. A table of the findings, biggest saving first:
   | Resource | Problem | Action | Saving / month | Confidence |
3. A fenced code block tagged `json` with the report (schema below). It must be valid JSON.

Only list what the user asked for (for "top 3", 3 findings). Say that all savings are estimates
and what they assume (each tool result has an `assumptions` or `basis` field).

## JSON schema

```json
{
  "summary": "one or two sentences",
  "month": "2026-09",
  "currency": "USD",
  "data_source": "floci-gcp emulator (sample data) | real GCP",
  "total_est_monthly_savings": 0.0,
  "findings": [
    {
      "id": "compute-legacy-ftp-idle",
      "service": "billing | gke | bigquery | compute | storage | logging",
      "resource": "VM, cluster/workload, bucket, query ...",
      "finding": "what is wasteful, in one sentence",
      "evidence": "the numbers that prove it, copied from tool results",
      "action": "the change we recommend",
      "change_action": "resize_vm | stop_vm | set_bucket_storage_class | add_bucket_lifecycle_rule | null",
      "est_monthly_savings": 0.0,
      "confidence": "high | medium | low",
      "effort": "low | medium | high",
      "risk": "what could go wrong"
    }
  ]
}
```

## Rules

- Every number is copied from a tool result. Never add up, round differently or invent numbers.
  `total_est_monthly_savings` is `total_estimated_monthly_saving` from `estimate_savings`, even
  when you list only some findings. If you did not call it, use `null`.
- `est_monthly_savings` is a number from a tool, or `null` when no tool estimates it.
- One root cause is one finding. Sort by `est_monthly_savings`, `null` last.
- Confidence: high = idle or unused resources; medium = rightsizing and query fixes;
  low = Spot, commitments, or anything that depends on future usage.
- `change_action` is set only when one of the allowed changes can apply the fix. Listing a
  finding is not approval to change anything; changes still go through propose and approve.
- Recommendations only: never say a change was made unless `apply_change` returned ok.
