"""Billing tools that run SQL on the Cloud Billing export (BigQuery). Read-only.

They need COST_DATA_SOURCE=bigquery; with the mock files they return an error saying so.
"""

import re
from statistics import median

from ..data import get_data_source
from ..data.bigquery_source import NET, BigQueryDataSource, BigQueryError

MAX_ROWS = 200
_NAME = re.compile(r"^[A-Za-z0-9 _.\-]{1,100}$")  # safe to put inside a SQL string
_MONTH = re.compile(r"^\d{4}-\d{2}$")
_WRITE_WORDS = re.compile(
    r"\b(insert|update|delete|merge|create|drop|alter|truncate|grant|revoke|export|load|call|declare|set|execute|begin|commit)\b",
    re.I)


def _source() -> BigQueryDataSource:
    source = get_data_source()
    if not isinstance(source, BigQueryDataSource):
        raise BigQueryError("This tool needs the billing export in BigQuery (COST_DATA_SOURCE=bigquery).")
    return source


def _error(exc: Exception) -> dict:
    return {"status": "error", "message": str(exc)}


def _month(source: BigQueryDataSource, month: str | None) -> str:
    """'YYYY-MM' -> 'YYYYMM'; empty means the latest month in the export."""
    if not month:
        return source.latest_month()
    if not _MONTH.match(month):
        raise BigQueryError("month must look like 2026-09.")
    return month.replace("-", "")


def _fmt(month: str) -> str:
    return f"{month[:4]}-{month[4:]}"


def get_daily_costs(month: str | None = None, service: str | None = None) -> dict:
    """Cost per day for one month (net of credits), with the biggest service each day.

    Args:
        month: Month as "YYYY-MM". Leave empty for the latest month.
        service: Only this service, e.g. "BigQuery". Leave empty for all services.
    """
    try:
        source = _source()
        m = _month(source, month)
        where = f"invoice.month = '{m}'"
        if service:
            if not _NAME.match(service):
                raise BigQueryError("service has characters that are not allowed.")
            where += f" AND service.description = '{service}'"
        rows = source.query(f"SELECT CAST(DATE(usage_start_time) AS STRING) AS day, service.description AS service, "
                            f"ROUND(SUM({NET}), 2) AS cost FROM {{billing_table}} WHERE {where} GROUP BY day, service")
    except BigQueryError as exc:
        return _error(exc)
    days: dict[str, dict] = {}
    for r in rows:
        d = days.setdefault(r["day"], {"day": r["day"], "cost": 0.0, "top_service": None, "top_service_cost": 0.0})
        cost = float(r["cost"])
        d["cost"] += cost
        if cost > d["top_service_cost"]:
            d["top_service"], d["top_service_cost"] = r["service"], cost
    out = [{**d, "cost": round(d["cost"], 2)} for d in sorted(days.values(), key=lambda d: d["day"])]
    return {"status": "ok", "month": _fmt(m), "service": service or "all", "days": out,
            "month_total": round(sum(d["cost"] for d in out), 2)}


def get_daily_spikes(month: str | None = None, threshold_pct: float = 50) -> dict:
    """Days when a service and project cost much more than usual (spike days).

    A spike is a day that costs more than its usual day (the median of the month) by
    threshold_pct percent or more.

    Args:
        month: Month as "YYYY-MM". Leave empty for the latest month.
        threshold_pct: How much above a normal day counts as a spike, in percent (default 50).
    """
    try:
        source = _source()
        m = _month(source, month)
        rows = source.query(f"SELECT CAST(DATE(usage_start_time) AS STRING) AS day, service.description AS service, "
                            f"project.id AS project, ROUND(SUM({NET}), 2) AS cost FROM {{billing_table}} "
                            f"WHERE invoice.month = '{m}' GROUP BY day, service, project")
    except BigQueryError as exc:
        return _error(exc)
    series: dict[tuple, list] = {}
    for r in rows:
        series.setdefault((r["service"], r["project"]), []).append((r["day"], float(r["cost"])))
    spikes = []
    for (service, project), points in series.items():
        usual = median(c for _, c in points)
        for day, cost in points:
            if usual > 0 and (cost - usual) / usual * 100 >= threshold_pct:
                spikes.append({"day": day, "service": service, "project": project, "cost": round(cost, 2),
                               "usual_day_cost": round(usual, 2), "extra_cost": round(cost - usual, 2),
                               "increase_pct": round((cost - usual) / usual * 100, 1)})
    spikes.sort(key=lambda s: -s["extra_cost"])
    return {"status": "ok", "month": _fmt(m), "threshold_pct": threshold_pct, "spikes": spikes,
            "note": "usual_day_cost is the median day of that service and project in the month."}


def get_top_resources(month: str | None = None, limit: int = 10) -> dict:
    """The most expensive resources (VMs, GKE workloads, buckets, databases) in a month.

    Args:
        month: Month as "YYYY-MM". Leave empty for the latest month.
        limit: How many resources to return (default 10, max 50).
    """
    try:
        source = _source()
        m = _month(source, month)
        rows = source.query(f"SELECT service.description AS service, project.id AS project, resource.name AS resource, "
                            f"ROUND(SUM({NET}), 2) AS cost FROM {{billing_table}} "
                            f"WHERE invoice.month = '{m}' AND resource.name IS NOT NULL "
                            f"GROUP BY service, project, resource ORDER BY cost DESC LIMIT {max(1, min(int(limit), 50))}")
    except (BigQueryError, ValueError) as exc:
        return _error(exc)
    return {"status": "ok", "month": _fmt(m),
            "resources": [{**r, "cost": float(r["cost"])} for r in rows]}


def get_unlabeled_spend(month: str | None = None, label_key: str = "team") -> dict:
    """Spend with no owner label: which resources have no label_key label, and how much they cost.

    Args:
        month: Month as "YYYY-MM". Leave empty for the latest month.
        label_key: The label every resource should have (default "team").
    """
    try:
        source = _source()
        m = _month(source, month)
        if not _NAME.match(label_key):
            raise BigQueryError("label_key has characters that are not allowed.")
        rows = source.query(f"SELECT service.description AS service, project.id AS project, resource.name AS resource, "
                            f"ROUND(SUM({NET}), 2) AS cost FROM {{billing_table}} WHERE invoice.month = '{m}' "
                            f"AND NOT EXISTS (SELECT 1 FROM UNNEST(labels) AS l WHERE l.key = '{label_key}') "
                            f"GROUP BY service, project, resource ORDER BY cost DESC")
        total = source.query(f"SELECT ROUND(SUM({NET}), 2) AS cost FROM {{billing_table}} WHERE invoice.month = '{m}'")
    except BigQueryError as exc:
        return _error(exc)
    items = [{**r, "cost": float(r["cost"])} for r in rows]
    unlabeled = round(sum(i["cost"] for i in items), 2)
    bill = float(total[0]["cost"]) if total and total[0]["cost"] else 0.0
    return {"status": "ok", "month": _fmt(m), "label_key": label_key, "unlabeled_cost": unlabeled,
            "total_cost": bill, "unlabeled_pct": round(unlabeled / bill * 100, 1) if bill else None, "items": items}


def run_billing_query(sql: str) -> dict:
    """Run your own read-only SQL (GoogleSQL) on the billing export, for questions no other tool answers.

    Write {billing_table} for the table. Only one SELECT (or WITH ... SELECT) statement; at most
    200 rows come back. Useful columns: service.description, sku.description, project.id,
    resource.name, labels (key/value list), usage_start_time, cost, credits (name/amount/type
    list), invoice.month ("YYYYMM"). Net cost = cost + the sum of credits.amount.
    Example: SELECT sku.description, SUM(cost) AS cost FROM {billing_table}
             WHERE invoice.month = '202609' GROUP BY 1 ORDER BY cost DESC LIMIT 10

    Args:
        sql: The SELECT statement.
    """
    text = sql.strip().rstrip(";").strip()
    if not re.match(r"^(select|with)\b", text, re.I) or ";" in text or "--" in text or "/*" in text:
        return _error(BigQueryError("Only one SELECT statement is allowed (no ';' and no comments)."))
    if _WRITE_WORDS.search(re.sub(r"'[^']*'", "''", text)):
        return _error(BigQueryError("Only read-only SELECT queries are allowed."))
    try:
        rows = _source().query(text)
    except BigQueryError as exc:
        return _error(exc)
    return {"status": "ok", "row_count": min(len(rows), MAX_ROWS), "truncated": len(rows) > MAX_ROWS,
            "rows": rows[:MAX_ROWS]}
