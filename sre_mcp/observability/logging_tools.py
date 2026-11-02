"""Read-only Cloud Logging tools.

Time and severity are filtered by the API. Text and resource matching is done
here, so it works the same on floci-gcp (limited filters) and real GCP.
"""

from collections import Counter, defaultdict

from . import client

SEVERITIES = ["DEFAULT", "DEBUG", "INFO", "NOTICE", "WARNING", "ERROR", "CRITICAL", "ALERT", "EMERGENCY"]
MAX_ENTRIES = 2000  # safety cap on entries read per call


def _rank(severity: str) -> int:
    return SEVERITIES.index(severity) if severity in SEVERITIES else 0


def _resource_name(entry: dict) -> str:
    res = entry.get("resource", {})
    labels = res.get("labels", {})
    if res.get("type") == "k8s_container":
        parts = [labels.get(k) for k in ("cluster_name", "namespace_name", "container_name")]
        return "/".join(p for p in parts if p) or "unknown-container"
    if res.get("type") == "gce_instance":
        return labels.get("instance_name") or labels.get("instance_id", "unknown-vm")
    return res.get("type", "unknown")


def _message(entry: dict) -> str:
    if "textPayload" in entry:
        return str(entry["textPayload"])
    payload = entry.get("jsonPayload", {})
    return str(payload.get("message") or payload)


def _simplify(entry: dict) -> dict:
    return {
        "time": entry.get("timestamp", ""),
        "severity": entry.get("severity", "DEFAULT"),
        "resource": _resource_name(entry),
        "log": entry.get("logName", "").rsplit("/", 1)[-1],
        "message": _message(entry),
    }


def _fetch(hours: int, min_severity: str | None) -> list[dict]:
    start, _ = client.window(hours)
    filt = f'timestamp>="{start}"'
    if min_severity:
        filt += f" AND severity>={min_severity}"
    body = {
        "resourceNames": [f"projects/{client.project()}"],
        "filter": filt,
        "orderBy": "timestamp desc",
        "pageSize": 500,
    }
    entries: list[dict] = []
    while len(entries) < MAX_ENTRIES:
        data = client.post("/v2/entries:list", body)
        entries.extend(data.get("entries", []))
        token = data.get("nextPageToken")
        if not token:
            break
        body["pageToken"] = token
    rows = [_simplify(e) for e in entries[:MAX_ENTRIES]]
    # Re-check time and severity locally in case the API ignored part of the filter.
    rows = [r for r in rows if r["time"] >= start]
    if min_severity:
        rows = [r for r in rows if _rank(r["severity"]) >= _rank(min_severity)]
    return sorted(rows, key=lambda r: r["time"], reverse=True)


def search_logs(
    query: str | None = None,
    severity: str | None = None,
    resource: str | None = None,
    hours: int = 24,
    limit: int = 50,
) -> dict:
    """Find log entries from the last `hours` hours, newest first.

    query: text the message must contain (case-insensitive).
    severity: minimum severity, e.g. WARNING or ERROR.
    resource: text the resource name must contain (VM name, cluster, namespace or container).
    """
    if severity is not None and severity.upper() not in SEVERITIES:
        return {"status": "error", "message": f"severity must be one of {', '.join(SEVERITIES)}."}
    try:
        rows = _fetch(hours, severity.upper() if severity else None)
    except client.ApiError as exc:
        return {"status": "error", "message": str(exc)}
    if query:
        rows = [r for r in rows if query.lower() in r["message"].lower()]
    if resource:
        rows = [r for r in rows if resource.lower() in r["resource"].lower()]
    return {
        "status": "ok",
        "hours": hours,
        "match_count": len(rows),
        "shown": min(limit, len(rows)),
        "entries": rows[:limit],
    }


def get_recent_errors(hours: int = 24, resource: str | None = None, limit: int = 10) -> dict:
    """ERROR and worse logs from the last `hours` hours, grouped by message, most frequent first."""
    try:
        rows = _fetch(hours, "ERROR")
    except client.ApiError as exc:
        return {"status": "error", "message": str(exc)}
    if resource:
        rows = [r for r in rows if resource.lower() in r["resource"].lower()]
    groups: dict[str, dict] = {}
    for r in rows:
        g = groups.setdefault(r["message"], {
            "message": r["message"],
            "count": 0,
            "severity": r["severity"],
            "resources": set(),
            "first_seen": r["time"],
            "last_seen": r["time"],
        })
        g["count"] += 1
        g["resources"].add(r["resource"])
        if _rank(r["severity"]) > _rank(g["severity"]):
            g["severity"] = r["severity"]
        g["first_seen"] = min(g["first_seen"], r["time"])
        g["last_seen"] = max(g["last_seen"], r["time"])
    top = sorted(groups.values(), key=lambda g: g["count"], reverse=True)[:limit]
    for g in top:
        g["resources"] = sorted(g["resources"])
    return {
        "status": "ok",
        "hours": hours,
        "total_errors": len(rows),
        "distinct_errors": len(groups),
        "top_errors": top,
    }


def get_log_summary(hours: int = 24) -> dict:
    """Count of log entries per severity and per resource for the last `hours` hours."""
    try:
        rows = _fetch(hours, None)
    except client.ApiError as exc:
        return {"status": "error", "message": str(exc)}
    by_sev = Counter(r["severity"] for r in rows)
    by_res: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        by_res[r["resource"]][r["severity"]] += 1
    resources = [
        {
            "resource": name,
            "total": sum(c.values()),
            "errors": sum(n for s, n in c.items() if _rank(s) >= _rank("ERROR")),
            "warnings": c.get("WARNING", 0),
        }
        for name, c in by_res.items()
    ]
    resources.sort(key=lambda r: (r["errors"], r["warnings"], r["total"]), reverse=True)
    return {
        "status": "ok",
        "hours": hours,
        "total_entries": len(rows),
        "by_severity": {s: by_sev[s] for s in SEVERITIES if by_sev[s]},
        "by_resource": resources,
    }
