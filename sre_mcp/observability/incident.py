"""Is an incident over? Decided in code from the signals, not by the AI reading old logs."""

from datetime import datetime, timezone

from . import client
from .logging_tools import _fetch
from .monitoring import HIGH_PCT, METRICS, _list_series, _value, series_name


def _time(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _matches(name: str, resource: str) -> bool:
    """'payments-api' matches 'prod-cluster/checkout/payments-api'."""
    return name == resource or name.rsplit("/", 1)[-1] == resource


def check_incident_status(resource: str, quiet_minutes: int = 15, hours: int = 6) -> dict:
    """Is the incident on this resource over? Checks its ERROR-or-worse logs and its CPU.

    Verdicts:
      "ongoing"     CPU is high now, or errors are still recent (within quiet_minutes) with no recovery.
      "recovering"  CPU is back to normal but errors are still recent.
      "resolved"    CPU is normal now and no errors since it recovered (or none for quiet_minutes).
      "no_errors"   no errors for this resource in the last `hours`.
    Old errors stay in the logs after a fix, so use this tool, not the raw logs, to decide
    whether a problem is still there. Best used on the resource at the root of the incident (a VM).

    Args:
        resource: VM name (e.g. "db-proxy") or GKE workload (e.g. "payments-api").
        quiet_minutes: Minutes without errors that count as quiet (default 15).
        hours: How far back to look (default 6).
    """
    try:
        errors = [e for e in _fetch(hours, "ERROR") if _matches(e["resource"], resource)]
        series = [s for s in _list_series(METRICS[("vm", "cpu")][0], hours) if _matches(series_name(s), resource)]
    except client.ApiError as exc:
        return {"status": "error", "message": str(exc)}

    now = datetime.now(timezone.utc)
    last_error = max((e["time"] for e in errors), default=None)
    minutes_since = round((now - _time(last_error)).total_seconds() / 60, 1) if last_error else None

    points = sorted(((_time(p["interval"]["endTime"]), _value(p) * METRICS[("vm", "cpu")][1])
                     for s in series for p in s.get("points", [])), key=lambda p: p[0])
    cpu = {"latest_pct": round(points[-1][1], 1), "time": client.to_rfc3339(points[-1][0])} if points else None
    cpu_high = bool(cpu and cpu["latest_pct"] >= HIGH_PCT)
    # When CPU came back to normal: the first normal point after the last high one.
    high_times = [t for t, v in points if v >= HIGH_PCT]
    recovered_at = next((t for t, v in points if high_times and t > high_times[-1] and v < HIGH_PCT), None)

    if last_error is None:
        verdict = "no_errors"
    elif cpu_high:
        verdict = "ongoing"
    elif (recovered_at and _time(last_error) < recovered_at) or minutes_since >= quiet_minutes:
        verdict = "resolved"
    elif cpu:
        verdict = "recovering"
    else:
        verdict = "ongoing"
    return {"status": "ok", "resource": resource, "verdict": verdict, "errors_in_window": len(errors),
            "window_hours": hours, "last_error": last_error, "minutes_since_last_error": minutes_since,
            "quiet_minutes": quiet_minutes, "cpu": cpu, "cpu_high_pct": HIGH_PCT,
            "cpu_recovered_at": client.to_rfc3339(recovered_at) if recovered_at else None,
            "checked_at": client.to_rfc3339(now)}
