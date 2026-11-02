"""Combines GKE, BigQuery, Compute Engine and Cloud Storage findings into one ranked savings list."""

from ..data import get_data_source
from . import billing
from .bigquery_cost import query_saving
from .compute_cost import cud_saving, is_idle, is_oversized, spot_saving
from .compute_cost import rightsizing_saving as vm_rightsizing_saving
from .gke_cost import SPOT_DISCOUNT, is_overprovisioned, rightsizing_saving
from .storage_cost import class_change_saving, cleanup_saving


def estimate_savings() -> dict:
    """Ranked list of cost-saving opportunities with estimated monthly savings (all are estimates)."""
    source = get_data_source()
    workloads = source.get_gke_workloads()["workloads"]
    queries = source.get_bigquery_queries()["queries"]
    compute = source.get_compute_resources()
    vms = compute["instances"]
    storage = source.get_storage_buckets()
    buckets, prices = storage["buckets"], storage["prices_per_gb"]

    # GKE: rightsize first, then Spot on what is left of batch workloads (no double counting).
    rightsize = sum(rightsizing_saving(w) for w in workloads if is_overprovisioned(w))
    spot = sum(
        (w["cost"] - (rightsizing_saving(w) if is_overprovisioned(w) else 0)) * SPOT_DISCOUNT
        for w in workloads
        if w["batch"]
    )
    bq = sum(query_saving(q) for q in queries)

    # Compute Engine: remove waste, rightsize, then Spot (batch) or CUD (steady) on the rightsized cost.
    vm_waste = sum(v["cost"] for v in vms if is_idle(v)) + sum(u["cost"] for u in compute["unused_resources"])
    vm_rightsize = sum(vm_rightsizing_saving(v) for v in vms if is_oversized(v))
    vm_spot = sum(spot_saving(v) for v in vms)
    vm_cud = sum(cud_saving(v) for v in vms)

    # Cloud Storage: cleanup and class changes cover different data, so they do not overlap.
    gcs_class = sum(class_change_saving(b, prices) for b in buckets)
    gcs_cleanup = sum(cleanup_saving(b, prices) for b in buckets)

    gke_cost = sum(w["cost"] for w in workloads)
    by_service = {r["service"]: r["cost"] for r in billing.get_cost_by_service()["by_service"]}
    bq_cost = by_service.get("BigQuery", 0)
    ce_cost = by_service.get("Compute Engine", 0)
    gcs_cost = by_service.get("Cloud Storage", 0)

    def ce_pct(saving: float) -> float | None:
        return round(saving / ce_cost * 100, 1) if ce_cost else None

    def gcs_pct(saving: float) -> float | None:
        return round(saving / gcs_cost * 100, 1) if gcs_cost else None

    opportunities = [
        {
            "title": "GKE: rightsize over-provisioned workloads",
            "service": "GKE",
            "estimated_monthly_saving": round(rightsize, 2),
            "pct_of_service_cost": round(rightsize / gke_cost * 100, 1),
            "basis": "Requests far above real CPU/memory use (see get_gke_overprovisioned_workloads).",
            "skill": "gke-cost-optimization",
        },
        {
            "title": "GKE: run batch workloads on Spot VMs",
            "service": "GKE",
            "estimated_monthly_saving": round(spot, 2),
            "pct_of_service_cost": round(spot / gke_cost * 100, 1),
            "basis": f"Batch workloads only, assuming a {int(SPOT_DISCOUNT * 100)}% Spot discount, after rightsizing.",
            "skill": "gke-cost-optimization",
        },
        {
            "title": "BigQuery: fix the most expensive queries",
            "service": "BigQuery",
            "estimated_monthly_saving": round(bq, 2),
            "pct_of_service_cost": round(bq / bq_cost * 100, 1) if bq_cost else None,
            "basis": "Partition filters, column pruning, caching (see get_bigquery_expensive_queries).",
            "skill": "bigquery-slot-cost-optimizer",
        },
        {
            "title": "Compute Engine: delete idle VMs and unused disks, snapshots and IPs",
            "service": "Compute Engine",
            "estimated_monthly_saving": round(vm_waste, 2),
            "pct_of_service_cost": ce_pct(vm_waste),
            "basis": "Full cost of idle VMs and unattached resources (see get_compute_waste).",
            "skill": "compute-engine-cost-optimization",
        },
        {
            "title": "Compute Engine: rightsize oversized VMs",
            "service": "Compute Engine",
            "estimated_monthly_saving": round(vm_rightsize, 2),
            "pct_of_service_cost": ce_pct(vm_rightsize),
            "basis": "Machine types far above real CPU/memory use (see get_compute_waste).",
            "skill": "compute-engine-cost-optimization",
        },
        {
            "title": "Compute Engine: run batch VMs on Spot VMs",
            "service": "Compute Engine",
            "estimated_monthly_saving": round(vm_spot, 2),
            "pct_of_service_cost": ce_pct(vm_spot),
            "basis": "Batch VMs only, after rightsizing (see get_compute_commitment_coverage).",
            "skill": "compute-engine-cost-optimization",
        },
        {
            "title": "Compute Engine: buy 1-year CUDs for steady production VMs",
            "service": "Compute Engine",
            "estimated_monthly_saving": round(vm_cud, 2),
            "pct_of_service_cost": ce_pct(vm_cud),
            "basis": "Uncovered steady VMs, on the rightsized cost (see get_compute_commitment_coverage).",
            "skill": "compute-engine-cost-optimization",
        },
        {
            "title": "Cloud Storage: move cold data to cheaper storage classes",
            "service": "Cloud Storage",
            "estimated_monthly_saving": round(gcs_class, 2),
            "pct_of_service_cost": gcs_pct(gcs_class),
            "basis": "Rarely read data moved to Nearline, Coldline or Archive (see get_storage_waste).",
            "skill": "cloud-storage-cost-optimization",
        },
        {
            "title": "Cloud Storage: delete old object versions and expired temp data",
            "service": "Cloud Storage",
            "estimated_monthly_saving": round(gcs_cleanup, 2),
            "pct_of_service_cost": gcs_pct(gcs_cleanup),
            "basis": "Lifecycle rules for old versions and data the owner marked deletable (see get_storage_waste).",
            "skill": "cloud-storage-cost-optimization",
        },
    ]
    opportunities.sort(key=lambda o: -o["estimated_monthly_saving"])
    total = round(sum(o["estimated_monthly_saving"] for o in opportunities), 2)
    bill = billing.get_cost_summary()["total_cost"]
    return {
        "status": "ok",
        "estimate": True,
        "opportunities": opportunities,
        "total_estimated_monthly_saving": total,
        "pct_of_total_bill": round(total / bill * 100, 1),
        "not_covered": "Cloud SQL, networking and other services: no detailed data yet.",
    }
