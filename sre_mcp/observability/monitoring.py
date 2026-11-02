"""Read-only Cloud Monitoring tools. Usage values are percentages (0-100)."""

from . import client

# Flags (shown to the user with the results).
HIGH_PCT = 80  # peak at or above this counts as high (possible saturation)
IDLE_PCT = 5  # average below this counts as idle

# (kind, metric) -> (Cloud Monitoring metric type, multiplier to get a percentage)
METRICS = {
    ("vm", "cpu"): ("compute.googleapis.com/instance/cpu/utilization", 100),
    ("vm", "memory"): ("agent.googleapis.com/memory/percent_used", 1),
    ("gke", "cpu"): ("kubernetes.io/container/cpu/request_utilization", 100),
    ("gke", "memory"): ("kubernetes.io/container/memory/request_utilization", 100),
}


def series_name(ts: dict) -> str:
    """Readable name: VM name, or cluster/namespace/container for GKE."""
    res = ts.get("resource", {})
    labels = res.get("labels", {})
    if res.get("type") == "k8s_container":
        parts = [labels.get(k) for k in ("cluster_name", "namespace_name", "container_name")]
        return "/".join(p for p in parts if p) or "unknown-container"
    if res.get("type") == "gce_instance":
        return ts.get("metric", {}).get("labels", {}).get("instance_name") or labels.get("instance_id", "unknown-vm")
    return res.get("type", "unknown")


def _value(point: dict) -> float:
    v = point.get("value", {})
    return float(v.get("doubleValue", v.get("int64Value", 0)))


def _list_series(metric_type: str, hours: int) -> list[dict]:
    start, end = client.window(hours)
    params = {
        "filter": f'metric.type="{metric_type}"',
        "interval.startTime": start,
        "interval.endTime": end,
    }
    series: list[dict] = []
    while True:
        data = client.get(f"/v3/projects/{client.project()}/timeSeries", params)
        series.extend(data.get("timeSeries", []))
        token = data.get("nextPageToken")
        if not token:
            return series
        params["pageToken"] = token


def list_metrics() -> dict:
    """List the metric types that have data in the project."""
    try:
        data = client.get(f"/v3/projects/{client.project()}/metricDescriptors")
    except client.ApiError as exc:
        return {"status": "error", "message": str(exc)}
    types = sorted(d["type"] for d in data.get("metricDescriptors", []))
    return {"status": "ok", "project": client.project(), "metric_count": len(types), "metrics": types}


def get_metric_timeseries(metric_type: str, resource_name: str | None = None, hours: int = 24) -> dict:
    """Raw data points for one metric type over the last `hours` hours.

    resource_name optionally keeps only series whose name contains it
    (VM name, or cluster/namespace/container for GKE).
    """
    try:
        series = _list_series(metric_type, hours)
    except client.ApiError as exc:
        return {"status": "error", "message": str(exc)}
    rows = []
    for ts in series:
        name = series_name(ts)
        if resource_name and resource_name not in name:
            continue
        points = sorted(
            ({"time": p["interval"]["endTime"], "value": round(_value(p), 4)} for p in ts.get("points", [])),
            key=lambda p: p["time"],
        )
        rows.append({"resource": name, "point_count": len(points), "points": points})
    if not rows:
        return {"status": "error", "message": f"No data for {metric_type} in the last {hours}h."}
    return {"status": "ok", "metric_type": metric_type, "hours": hours, "series": rows}


def get_resource_utilization(kind: str = "vm", metric: str = "cpu", hours: int = 24) -> dict:
    """Average, peak and latest usage (%) per VM or GKE container, with high and idle flags.

    kind: "vm" or "gke". metric: "cpu" or "memory".
    """
    key = (kind.lower(), metric.lower())
    if key not in METRICS:
        return {"status": "error", "message": "kind must be 'vm' or 'gke'; metric must be 'cpu' or 'memory'."}
    metric_type, scale = METRICS[key]
    try:
        series = _list_series(metric_type, hours)
    except client.ApiError as exc:
        return {"status": "error", "message": str(exc)}
    rows = []
    for ts in series:
        points = sorted(ts.get("points", []), key=lambda p: p["interval"]["endTime"])
        values = [_value(p) * scale for p in points]
        if not values:
            continue
        avg, peak = sum(values) / len(values), max(values)
        flag = "high" if peak >= HIGH_PCT else "idle" if avg < IDLE_PCT else "normal"
        rows.append({
            "resource": series_name(ts),
            "avg_pct": round(avg, 1),
            "peak_pct": round(peak, 1),
            "latest_pct": round(values[-1], 1),
            "flag": flag,
        })
    if not rows:
        return {"status": "error", "message": f"No {metric} data for {kind} in the last {hours}h."}
    rows.sort(key=lambda r: r["peak_pct"], reverse=True)
    return {
        "status": "ok",
        "kind": kind,
        "metric": metric,
        "metric_type": metric_type,
        "hours": hours,
        "resource_count": len(rows),
        "high_count": sum(r["flag"] == "high" for r in rows),
        "idle_count": sum(r["flag"] == "idle" for r in rows),
        "resources": rows,
        "assumptions": f"high = peak >= {HIGH_PCT}%, idle = average < {IDLE_PCT}%.",
    }
