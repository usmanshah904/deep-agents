"""Read-only billing tools. Costs are in USD per month."""

from collections import defaultdict

from ..data import get_data_source


def _records() -> list[dict]:
    return get_data_source().get_billing_records()


def _resolve_month(records: list[dict], month: str | None) -> str | None:
    months = sorted({r["month"] for r in records})
    if month is None:
        return months[-1] if months else None
    return month if month in months else None


def _previous_month(records: list[dict], month: str) -> str | None:
    earlier = sorted({r["month"] for r in records if r["month"] < month})
    return earlier[-1] if earlier else None


def _group(records: list[dict], month: str, key: str) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for r in records:
        if r["month"] == month:
            totals[r[key]] += r["cost"]
    return dict(totals)


def _pct(new: float, old: float) -> float | None:
    return round((new - old) / old * 100, 1) if old else None


_NO_DATA = {"status": "error", "message": "No billing data for that month."}


def _breakdown(month: str | None, key: str) -> dict:
    records = _records()
    month = _resolve_month(records, month)
    if month is None:
        return _NO_DATA
    totals = _group(records, month, key)
    total = sum(totals.values())
    rows = [
        {key: name, "cost": round(cost, 2), "share_pct": round(cost / total * 100, 1)}
        for name, cost in sorted(totals.items(), key=lambda kv: -kv[1])
    ]
    return {"status": "ok", "month": month, "total_cost": round(total, 2), f"by_{key}": rows}


def get_cost_summary(month: str | None = None) -> dict:
    """Total GCP cost for a month, with the change vs the previous month.

    Args:
        month: Month as "YYYY-MM". Leave empty for the latest month.
    """
    records = _records()
    month = _resolve_month(records, month)
    if month is None:
        return _NO_DATA
    total = sum(_group(records, month, "service").values())
    result = {"status": "ok", "month": month, "total_cost": round(total, 2)}
    prev = _previous_month(records, month)
    if prev:
        prev_total = sum(_group(records, prev, "service").values())
        result.update(
            previous_month=prev,
            previous_total_cost=round(prev_total, 2),
            change_amount=round(total - prev_total, 2),
            change_pct=_pct(total, prev_total),
        )
    return result


def get_cost_by_service(month: str | None = None) -> dict:
    """Cost per GCP service (GKE, BigQuery, ...) for a month, largest first.

    Args:
        month: Month as "YYYY-MM". Leave empty for the latest month.
    """
    return _breakdown(month, "service")


def get_cost_by_project(month: str | None = None) -> dict:
    """Cost per GCP project for a month, largest first.

    Args:
        month: Month as "YYYY-MM". Leave empty for the latest month.
    """
    return _breakdown(month, "project")


def compare_months(month: str | None = None) -> dict:
    """Which services changed most vs the previous month. Use for "why did the bill go up?".

    Args:
        month: Month as "YYYY-MM". Leave empty for the latest month.
    """
    records = _records()
    month = _resolve_month(records, month)
    if month is None:
        return _NO_DATA
    prev = _previous_month(records, month)
    if prev is None:
        return {"status": "error", "message": f"No earlier month to compare with {month}."}
    now = _group(records, month, "service")
    before = _group(records, prev, "service")
    rows = []
    for service in sorted(set(now) | set(before)):
        cur, old = now.get(service, 0.0), before.get(service, 0.0)
        rows.append(
            {
                "service": service,
                "current_cost": round(cur, 2),
                "previous_cost": round(old, 2),
                "change_amount": round(cur - old, 2),
                "change_pct": _pct(cur, old),
            }
        )
    rows.sort(key=lambda r: -r["change_amount"])
    return {
        "status": "ok",
        "month": month,
        "previous_month": prev,
        "current_total_cost": round(sum(now.values()), 2),
        "previous_total_cost": round(sum(before.values()), 2),
        "total_change_amount": round(sum(r["change_amount"] for r in rows), 2),
        "total_change_pct": _pct(sum(now.values()), sum(before.values())),
        "by_service": rows,
    }
