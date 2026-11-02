"""MCP server "gcp-sre-mcp" with 32 GCP tools. Runs over stdio for any MCP app.

- 20 cost tools (sre_mcp/cost): billing from the Cloud Billing export in BigQuery
  (COST_DATA_SOURCE=bigquery) or the mock files (COST_DATA_SOURCE=mock).
- 7 monitoring and logging tools (sre_mcp/observability): floci-gcp (OBS_API_URL), real GCP later.
- 5 change tools (sre_mcp/changes). get_inventory, propose_change, cancel_change and
  list_changes change nothing. apply_change makes a change, only after the user approves that
  change ID (agent rule + approval pause in agent.py). Local floci-gcp emulator only.

Run: python -m sre_mcp
"""

from mcp.server.fastmcp import FastMCP

from .changes.manager import apply_change, cancel_change, get_inventory, list_changes, propose_change
from .cost.tools.bigquery_cost import get_bigquery_expensive_queries
from .cost.tools.billing import compare_months, get_cost_by_project, get_cost_by_service, get_cost_summary
from .cost.tools.billing_sql import (
    get_daily_costs,
    get_daily_spikes,
    get_top_resources,
    get_unlabeled_spend,
    run_billing_query,
)
from .cost.tools.compute_cost import (
    get_compute_commitment_coverage,
    get_compute_cost_by_instance,
    get_compute_waste,
)
from .cost.tools.gke_cost import (
    get_gke_cost_by_cluster,
    get_gke_cost_by_namespace,
    get_gke_overprovisioned_workloads,
    get_gke_top_workloads,
)
from .cost.tools.savings import estimate_savings
from .cost.tools.storage_cost import get_storage_cost_by_bucket, get_storage_waste
from .observability.incident import check_incident_status
from .observability.logging_tools import get_log_summary, get_recent_errors, search_logs
from .observability.monitoring import get_metric_timeseries, get_resource_utilization, list_metrics

# Order matters: the dashboard groups tools as 20 cost, 7 observability, 5 changes.
COST_TOOLS = [
    get_cost_summary, get_cost_by_service, get_cost_by_project, compare_months,
    get_gke_cost_by_cluster, get_gke_cost_by_namespace, get_gke_top_workloads, get_gke_overprovisioned_workloads,
    get_bigquery_expensive_queries,
    get_compute_cost_by_instance, get_compute_waste, get_compute_commitment_coverage,
    get_storage_cost_by_bucket, get_storage_waste,
    estimate_savings,
    get_daily_costs, get_daily_spikes, get_top_resources, get_unlabeled_spend, run_billing_query,
]
OBSERVABILITY_TOOLS = [list_metrics, get_metric_timeseries, get_resource_utilization,
                       search_logs, get_recent_errors, get_log_summary, check_incident_status]
CHANGE_TOOLS = [get_inventory, propose_change, apply_change, cancel_change, list_changes]
TOOLS = COST_TOOLS + OBSERVABILITY_TOOLS + CHANGE_TOOLS

mcp = FastMCP("gcp-sre-mcp", log_level="WARNING")
for tool in TOOLS:
    mcp.tool()(tool)
