"""Read-only Cloud Storage cost tools. Costs are USD for the month in the data."""

from ..data import get_data_source

# Savings assumptions (shown to the user with every estimate).
# Cold data moves to the cheapest class whose minimum storage time fits how long it goes unread.
CLASS_BY_IDLE_DAYS = ((365, "ARCHIVE"), (90, "COLDLINE"), (30, "NEARLINE"))
HIGH_EGRESS_PCT = 30  # egress above this share of a bucket's cost is flagged


def _data() -> dict:
    return get_data_source().get_storage_buckets()


def target_class(b: dict, prices: dict) -> str | None:
    """Cheaper storage class for the bucket's cold data, or None if it should stay."""
    for days, cls in CLASS_BY_IDLE_DAYS:
        if b["cold_data_last_read_days"] >= days:
            return cls if prices[cls] < prices[b["storage_class"]] else None
    return None


def cold_gb(b: dict) -> float:
    """Cold data that is kept (deletable data is not counted twice)."""
    return (b["current_gb"] - b["deletable_gb"]) * b["cold_data_pct"] / 100


def class_change_saving(b: dict, prices: dict) -> float:
    cls = target_class(b, prices)
    return cold_gb(b) * (prices[b["storage_class"]] - prices[cls]) if cls else 0.0


def cleanup_saving(b: dict, prices: dict) -> float:
    """Deleting old object versions and data the owner's policy allows to go."""
    return (b["noncurrent_gb"] + b["deletable_gb"]) * prices[b["storage_class"]]


def get_storage_cost_by_bucket(limit: int = 10, project: str | None = None) -> dict:
    """Cloud Storage cost per bucket, largest first, split into storage, operations and egress.

    Args:
        limit: How many buckets to return (default 10).
        project: Only this project (for example "prod"). Leave empty for all projects.
    """
    data = _data()
    buckets = [b for b in data["buckets"] if project in (None, b["project"])]
    if not buckets:
        return {"status": "error", "message": f"No Cloud Storage data for project '{project}'."}
    total = sum(b["cost"] for b in buckets)
    keys = ("name", "project", "purpose", "storage_class", "current_gb", "noncurrent_gb",
            "storage_cost", "operations_cost", "egress_cost", "cost")
    rows = [
        {**{k: b[k] for k in keys}, "share_pct": round(b["cost"] / total * 100, 1)}
        for b in sorted(buckets, key=lambda b: -b["cost"])[: max(1, limit)]
    ]
    return {
        "status": "ok",
        "month": data["month"],
        "total_storage_cost": round(total, 2),
        "storage_cost": round(sum(b["storage_cost"] for b in buckets), 2),
        "operations_cost": round(sum(b["operations_cost"] for b in buckets), 2),
        "egress_cost": round(sum(b["egress_cost"] for b in buckets), 2),
        "by_bucket": rows,
    }


def get_storage_waste() -> dict:
    """Cold data in a too-expensive storage class, old object versions, deletable data, buckets with no
    lifecycle rules, and high network egress, with estimated monthly savings."""
    data = _data()
    prices = data["prices_per_gb"]
    class_changes, cleanups, no_lifecycle, high_egress = [], [], [], []
    for b in data["buckets"]:
        cls = target_class(b, prices)
        if cls:
            class_changes.append(
                {
                    "bucket": b["name"],
                    "project": b["project"],
                    "current_class": b["storage_class"],
                    "target_class": cls,
                    "cold_gb": round(cold_gb(b), 2),
                    "cold_data_last_read_days": b["cold_data_last_read_days"],
                    "estimated_monthly_saving": round(class_change_saving(b, prices), 2),
                }
            )
        if b["noncurrent_gb"] or b["deletable_gb"]:
            cleanups.append(
                {
                    "bucket": b["name"],
                    "project": b["project"],
                    "noncurrent_gb": b["noncurrent_gb"],
                    "deletable_gb": b["deletable_gb"],
                    "estimated_monthly_saving": round(cleanup_saving(b, prices), 2),
                }
            )
        if (cls or b["noncurrent_gb"] or b["deletable_gb"]) and not b["lifecycle_rules"]:
            no_lifecycle.append(b["name"])
        if b["cost"] and b["egress_cost"] / b["cost"] * 100 > HIGH_EGRESS_PCT:
            high_egress.append(
                {"bucket": b["name"], "egress_cost": b["egress_cost"],
                 "egress_pct_of_bucket": round(b["egress_cost"] / b["cost"] * 100, 1)}
            )
    class_changes.sort(key=lambda r: -r["estimated_monthly_saving"])
    cleanups.sort(key=lambda r: -r["estimated_monthly_saving"])
    saving = sum(r["estimated_monthly_saving"] for r in class_changes + cleanups)
    total = sum(b["cost"] for b in data["buckets"])
    return {
        "status": "ok",
        "month": data["month"],
        "estimate": True,
        "assumptions": (
            "Cold data moves to Nearline if unread 30+ days, Coldline if 90+, Archive if 365+. "
            "Saving = cold GB x price difference; reading it back later adds retrieval fees. "
            "Old object versions and data marked deletable are removed by lifecycle rules; saving = their "
            "storage cost. Egress is flagged only, with no saving estimate."
        ),
        "class_changes": class_changes,
        "cleanups": cleanups,
        "buckets_without_lifecycle_rules": no_lifecycle,
        "high_egress": high_egress,
        "total_estimated_monthly_saving": round(saving, 2),
        "pct_of_storage_cost": round(saving / total * 100, 1) if total else None,
    }
