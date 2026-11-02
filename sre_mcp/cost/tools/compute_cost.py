"""Read-only Compute Engine cost tools. Costs are USD for the month in the data."""

from ..data import get_data_source

# Savings assumptions (shown to the user with every estimate).
IDLE_CPU_PCT = 5  # below this average CPU use, a VM counts as idle
UTIL_THRESHOLD_PCT = 50  # below this peak of CPU/memory use, a VM counts as oversized
HEADROOM = 1.3  # keep the new machine size 30% above real usage
CAPTURE_RATE = 0.5  # assume only half of the theoretical waste is realistically saved
SPOT_DISCOUNT = 0.6  # typical Spot VM discount for batch work
STEADY_UPTIME_PCT = 90  # VMs running at least this much of the month suit a commitment
CUD_NET_DISCOUNT = 0.2  # 1-year CUD saving on top of the sustained use discount already in the cost


def _data() -> dict:
    return get_data_source().get_compute_resources()


def is_idle(vm: dict) -> bool:
    return vm["cpu_util_pct"] < IDLE_CPU_PCT


def is_oversized(vm: dict) -> bool:
    return not is_idle(vm) and max(vm["cpu_util_pct"], vm["mem_util_pct"]) < UTIL_THRESHOLD_PCT


def rightsizing_saving(vm: dict) -> float:
    """Estimated monthly saving if the VM moves to a machine sized for peak usage * HEADROOM."""
    target = max(vm["cpu_util_pct"], vm["mem_util_pct"]) / 100 * HEADROOM
    return vm["cost"] * max(0.0, 1 - target) * CAPTURE_RATE


def _cost_after_rightsizing(vm: dict) -> float:
    return vm["cost"] - (rightsizing_saving(vm) if is_oversized(vm) else 0)


def spot_saving(vm: dict) -> float:
    """Spot saving for a batch VM, counted after rightsizing (no double counting)."""
    return _cost_after_rightsizing(vm) * SPOT_DISCOUNT if vm["batch"] and not is_idle(vm) else 0.0


def is_cud_candidate(vm: dict) -> bool:
    return (
        vm["env"] == "prod"
        and not vm["batch"]
        and not is_idle(vm)
        and not vm["cud_covered"]
        and vm["uptime_pct"] >= STEADY_UPTIME_PCT
    )


def cud_saving(vm: dict) -> float:
    """Commitment saving on the rightsized cost, so we never commit to waste."""
    return _cost_after_rightsizing(vm) * CUD_NET_DISCOUNT if is_cud_candidate(vm) else 0.0


def _filter(items: list[dict], project: str | None) -> list[dict]:
    return [i for i in items if project in (None, i["project"])]


def get_compute_cost_by_instance(limit: int = 10, project: str | None = None) -> dict:
    """Compute Engine cost per VM (largest first) plus the cost of unused disks, snapshots and IPs.

    Args:
        limit: How many VMs to return (default 10).
        project: Only this project (for example "prod"). Leave empty for all projects.
    """
    data = _data()
    vms = _filter(data["instances"], project)
    unused = _filter(data["unused_resources"], project)
    if not vms and not unused:
        return {"status": "error", "message": f"No Compute Engine data for project '{project}'."}
    vm_cost = sum(v["cost"] for v in vms)
    unused_cost = sum(u["cost"] for u in unused)
    total = vm_cost + unused_cost
    rows = [
        {
            **{k: v[k] for k in ("name", "project", "machine_type", "cost", "cpu_util_pct", "mem_util_pct")},
            "share_pct": round(v["cost"] / total * 100, 1),
        }
        for v in sorted(vms, key=lambda v: -v["cost"])[: max(1, limit)]
    ]
    return {
        "status": "ok",
        "month": data["month"],
        "total_compute_cost": round(total, 2),
        "vm_cost": round(vm_cost, 2),
        "unused_resources_cost": round(unused_cost, 2),
        "vm_count": len(vms),
        "top_instances": rows,
    }


def get_compute_waste() -> dict:
    """Idle VMs, oversized VMs and unused disks, snapshots and IPs, with estimated monthly savings."""
    data = _data()
    idle = [
        {**{k: v[k] for k in ("name", "project", "machine_type", "cost", "cpu_util_pct")},
         "estimated_monthly_saving": round(v["cost"], 2)}
        for v in data["instances"]
        if is_idle(v)
    ]
    oversized = [
        {
            **{k: v[k] for k in ("name", "project", "machine_type", "cost", "cpu_util_pct", "mem_util_pct")},
            "estimated_monthly_saving": round(rightsizing_saving(v), 2),
        }
        for v in data["instances"]
        if is_oversized(v)
    ]
    oversized.sort(key=lambda r: -r["estimated_monthly_saving"])
    unused = [{**u, "estimated_monthly_saving": round(u["cost"], 2)} for u in data["unused_resources"]]
    unused.sort(key=lambda r: -r["estimated_monthly_saving"])
    saving = sum(r["estimated_monthly_saving"] for r in idle + oversized + unused)
    total = sum(v["cost"] for v in data["instances"]) + sum(u["cost"] for u in data["unused_resources"])
    return {
        "status": "ok",
        "month": data["month"],
        "estimate": True,
        "assumptions": (
            f"Idle = average CPU below {IDLE_CPU_PCT}%; saving is the full VM cost if it is deleted. "
            f"Oversized = CPU and memory both below {UTIL_THRESHOLD_PCT}%; machine resized to peak usage + "
            f"{int((HEADROOM - 1) * 100)}% headroom, and only {int(CAPTURE_RATE * 100)}% of that waste is "
            "counted as saved. Unused disks, snapshots and IPs: full cost saved if deleted after a backup check."
        ),
        "idle_vms": idle,
        "oversized_vms": oversized,
        "unused_resources": unused,
        "total_estimated_monthly_saving": round(saving, 2),
        "pct_of_compute_cost": round(saving / total * 100, 1) if total else None,
    }


def get_compute_commitment_coverage() -> dict:
    """Discount coverage: steady production VMs that could use a committed use discount (CUD), and
    batch VMs that could run on Spot VMs, with estimated monthly savings."""
    data = _data()
    steady = [
        v for v in data["instances"]
        if v["env"] == "prod" and not v["batch"] and not is_idle(v) and v["uptime_pct"] >= STEADY_UPTIME_PCT
    ]
    steady_cost = sum(v["cost"] for v in steady)
    covered_cost = sum(v["cost"] for v in steady if v["cud_covered"])
    candidates = [
        {
            **{k: v[k] for k in ("name", "project", "machine_type", "cost", "uptime_pct")},
            "cost_after_rightsizing": round(_cost_after_rightsizing(v), 2),
            "estimated_monthly_saving": round(cud_saving(v), 2),
        }
        for v in data["instances"]
        if is_cud_candidate(v)
    ]
    candidates.sort(key=lambda r: -r["estimated_monthly_saving"])
    spot = [
        {
            **{k: v[k] for k in ("name", "project", "machine_type", "cost")},
            "estimated_monthly_saving": round(spot_saving(v), 2),
        }
        for v in data["instances"]
        if spot_saving(v) > 0
    ]
    spot.sort(key=lambda r: -r["estimated_monthly_saving"])
    return {
        "status": "ok",
        "month": data["month"],
        "estimate": True,
        "assumptions": (
            f"Steady = production, non-batch, running at least {STEADY_UPTIME_PCT}% of the month. "
            f"A 1-year CUD saves about {int(CUD_NET_DISCOUNT * 100)}% more than the sustained use discount "
            "already in the cost. Commit only to the rightsized size. "
            f"Batch VMs: Spot assumed {int(SPOT_DISCOUNT * 100)}% cheaper, after rightsizing."
        ),
        "steady_vm_cost": round(steady_cost, 2),
        "covered_cost": round(covered_cost, 2),
        "coverage_pct": round(covered_cost / steady_cost * 100, 1) if steady_cost else None,
        "cud_candidates": candidates,
        "cud_estimated_monthly_saving": round(sum(r["estimated_monthly_saving"] for r in candidates), 2),
        "spot_candidates": spot,
        "spot_estimated_monthly_saving": round(sum(r["estimated_monthly_saving"] for r in spot), 2),
    }
