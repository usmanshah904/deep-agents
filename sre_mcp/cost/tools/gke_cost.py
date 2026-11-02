"""Read-only GKE cost tools. Costs are USD for the month in the data."""

from collections import defaultdict

from ..data import get_data_source

# Savings assumptions (shown to the user with every estimate).
HEADROOM = 1.3  # keep requests 30% above real usage
CAPTURE_RATE = 0.5  # assume only half of the theoretical waste is realistically saved
UTIL_THRESHOLD_PCT = 50  # below this average CPU/memory use, a workload counts as over-provisioned
SPOT_DISCOUNT = 0.6  # typical Spot VM discount for batch work


def _data() -> dict:
    return get_data_source().get_gke_workloads()


def _util_pct(used: float, requested: float) -> float:
    return round(used / requested * 100, 1) if requested else 0.0


def avg_util_pct(w: dict) -> float:
    return round(
        (_util_pct(w["cpu_used"], w["cpu_requested"]) + _util_pct(w["mem_used_gb"], w["mem_requested_gb"])) / 2,
        1,
    )


def rightsizing_saving(w: dict) -> float:
    """Estimated monthly saving if requests are lowered to usage * HEADROOM."""
    ratios = []
    for requested, used in ((w["cpu_requested"], w["cpu_used"]), (w["mem_requested_gb"], w["mem_used_gb"])):
        ratios.append(max(0.0, 1 - used * HEADROOM / requested) if requested else 0.0)
    return w["cost"] * (sum(ratios) / len(ratios)) * CAPTURE_RATE


def is_overprovisioned(w: dict) -> bool:
    return avg_util_pct(w) < UTIL_THRESHOLD_PCT


def _group_cost(workloads: list[dict], keys: tuple[str, ...]) -> list[dict]:
    totals: dict[tuple, float] = defaultdict(float)
    for w in workloads:
        totals[tuple(w[k] for k in keys)] += w["cost"]
    grand = sum(totals.values())
    rows = [
        {**dict(zip(keys, k)), "cost": round(c, 2), "share_pct": round(c / grand * 100, 1)}
        for k, c in sorted(totals.items(), key=lambda kv: -kv[1])
    ]
    return rows


def get_gke_cost_by_cluster() -> dict:
    """GKE cost per cluster (with Standard/Autopilot mode), largest first."""
    data = _data()
    workloads = data["workloads"]
    modes = {w["cluster"]: w["cluster_mode"] for w in workloads}
    rows = _group_cost(workloads, ("cluster",))
    for r in rows:
        r["mode"] = modes[r["cluster"]]
    return {
        "status": "ok",
        "month": data["month"],
        "total_gke_cost": round(sum(w["cost"] for w in workloads), 2),
        "by_cluster": rows,
    }


def get_gke_cost_by_namespace(cluster: str | None = None) -> dict:
    """GKE cost per namespace, largest first.

    Args:
        cluster: Only this cluster (for example "prod-cluster"). Leave empty for all clusters.
    """
    data = _data()
    workloads = [w for w in data["workloads"] if cluster in (None, w["cluster"])]
    if not workloads:
        return {"status": "error", "message": f"No GKE data for cluster '{cluster}'."}
    return {
        "status": "ok",
        "month": data["month"],
        "total_cost": round(sum(w["cost"] for w in workloads), 2),
        "by_namespace": _group_cost(workloads, ("cluster", "namespace")),
    }


def get_gke_top_workloads(limit: int = 10, cluster: str | None = None) -> dict:
    """Most expensive GKE workloads, largest first.

    Args:
        limit: How many workloads to return (default 10).
        cluster: Only this cluster. Leave empty for all clusters.
    """
    data = _data()
    workloads = [w for w in data["workloads"] if cluster in (None, w["cluster"])]
    if not workloads:
        return {"status": "error", "message": f"No GKE data for cluster '{cluster}'."}
    rows = [
        {k: w[k] for k in ("cluster", "namespace", "workload", "cost")}
        for w in sorted(workloads, key=lambda w: -w["cost"])[: max(1, limit)]
    ]
    return {"status": "ok", "month": data["month"], "top_workloads": rows}


def get_gke_overprovisioned_workloads() -> dict:
    """Workloads that request far more CPU/memory than they use, with estimated monthly savings."""
    data = _data()
    rows = []
    for w in data["workloads"]:
        if not is_overprovisioned(w):
            continue
        rows.append(
            {
                "cluster": w["cluster"],
                "namespace": w["namespace"],
                "workload": w["workload"],
                "cost": w["cost"],
                "cpu_requested": w["cpu_requested"],
                "cpu_used": w["cpu_used"],
                "mem_requested_gb": w["mem_requested_gb"],
                "mem_used_gb": w["mem_used_gb"],
                "avg_utilization_pct": avg_util_pct(w),
                "estimated_monthly_saving": round(rightsizing_saving(w), 2),
            }
        )
    rows.sort(key=lambda r: -r["estimated_monthly_saving"])
    return {
        "status": "ok",
        "month": data["month"],
        "estimate": True,
        "assumptions": (
            f"Over-provisioned = average CPU/memory use below {UTIL_THRESHOLD_PCT}% of requests. "
            f"Requests lowered to usage + {int((HEADROOM - 1) * 100)}% headroom; "
            f"only {int(CAPTURE_RATE * 100)}% of that waste is counted as saved."
        ),
        "overprovisioned": rows,
        "total_estimated_monthly_saving": round(sum(r["estimated_monthly_saving"] for r in rows), 2),
    }
