"""Monitoring and logging tools, with the API faked (no floci needed)."""

from datetime import datetime, timedelta, timezone

import pytest

from sre_mcp.observability import client, logging_tools, monitoring


def _ago(minutes: int) -> str:
    return client.to_rfc3339(datetime.now(timezone.utc) - timedelta(minutes=minutes))


def _vm_series(name: str, values: list[float]) -> dict:
    return {
        "metric": {"type": "compute.googleapis.com/instance/cpu/utilization", "labels": {"instance_name": name}},
        "resource": {"type": "gce_instance", "labels": {"instance_id": name}},
        "points": [
            {"interval": {"endTime": _ago(60 * (len(values) - i))}, "value": {"doubleValue": v}}
            for i, v in enumerate(values)
        ],
    }


def _log(severity: str, message: str, minutes: int, namespace: str = "checkout") -> dict:
    return {
        "logName": "projects/demo-project/logs/app",
        "resource": {
            "type": "k8s_container",
            "labels": {"cluster_name": "prod", "namespace_name": namespace, "container_name": "api"},
        },
        "severity": severity,
        "textPayload": message,
        "timestamp": _ago(minutes),
    }


SERIES = [_vm_series("busy-vm", [0.5, 0.6, 0.95]), _vm_series("idle-vm", [0.01, 0.02, 0.01]), _vm_series("ok-vm", [0.3, 0.4])]
LOGS = [
    _log("ERROR", "db timeout", 10),
    _log("ERROR", "db timeout", 20),
    _log("CRITICAL", "pool exhausted", 30, namespace="db"),
    _log("WARNING", "slow response", 40),
    _log("INFO", "ok", 50),
    _log("ERROR", "too old", 60 * 48),  # outside a 24h window
]


@pytest.fixture(autouse=True)
def fake_api(monkeypatch):
    def get(path, params=None):
        if path.endswith("/metricDescriptors"):
            return {"metricDescriptors": [{"type": "b.metric"}, {"type": "a.metric"}]}
        wanted = params["filter"].split('"')[1]
        return {"timeSeries": [s for s in SERIES if s["metric"]["type"] == wanted]}

    def post(path, body):
        assert path == "/v2/entries:list"
        return {"entries": LOGS}

    monkeypatch.setattr(client, "get", get)
    monkeypatch.setattr(client, "post", post)


def test_list_metrics_sorted():
    r = monitoring.list_metrics()
    assert r["metrics"] == ["a.metric", "b.metric"] and r["metric_count"] == 2


def test_utilization_flags_and_order():
    r = monitoring.get_resource_utilization("vm", "cpu")
    rows = {x["resource"]: x for x in r["resources"]}
    assert rows["busy-vm"]["flag"] == "high" and rows["busy-vm"]["peak_pct"] == 95.0
    assert rows["busy-vm"]["latest_pct"] == 95.0
    assert rows["idle-vm"]["flag"] == "idle"
    assert rows["ok-vm"]["flag"] == "normal"
    assert r["resources"][0]["resource"] == "busy-vm"
    assert (r["high_count"], r["idle_count"]) == (1, 1)


def test_utilization_bad_input_and_no_data():
    assert monitoring.get_resource_utilization("db", "cpu")["status"] == "error"
    assert monitoring.get_resource_utilization("gke", "cpu")["status"] == "error"  # no GKE series


def test_timeseries_filter_by_resource():
    r = monitoring.get_metric_timeseries("compute.googleapis.com/instance/cpu/utilization", "busy")
    assert [s["resource"] for s in r["series"]] == ["busy-vm"]
    assert r["series"][0]["points"][-1]["value"] == 0.95
    assert monitoring.get_metric_timeseries("nope")["status"] == "error"


def test_recent_errors_grouped_and_window_applied():
    r = logging_tools.get_recent_errors()
    assert r["total_errors"] == 3 and r["distinct_errors"] == 2
    top = r["top_errors"][0]
    assert top["message"] == "db timeout" and top["count"] == 2
    assert top["first_seen"] < top["last_seen"]
    assert logging_tools.get_recent_errors(resource="db")["total_errors"] == 1


def test_search_logs_filters_locally():
    assert logging_tools.search_logs(query="TIMEOUT")["match_count"] == 2
    assert logging_tools.search_logs(severity="warning")["match_count"] == 4
    assert logging_tools.search_logs(resource="prod/db")["match_count"] == 1
    r = logging_tools.search_logs(limit=1)
    assert r["match_count"] == 5 and r["shown"] == 1
    assert r["entries"][0]["message"] == "db timeout"  # newest first
    assert logging_tools.search_logs(severity="LOUD")["status"] == "error"


def test_log_summary():
    r = logging_tools.get_log_summary()
    assert r["total_entries"] == 5
    assert r["by_severity"] == {"INFO": 1, "WARNING": 1, "ERROR": 2, "CRITICAL": 1}
    assert r["by_resource"][0] == {"resource": "prod/checkout/api", "total": 4, "errors": 2, "warnings": 1}


def test_api_down_returns_error(monkeypatch):
    def down(*args, **kwargs):
        raise client.ApiError("Cannot reach floci")

    monkeypatch.setattr(client, "get", down)
    monkeypatch.setattr(client, "post", down)
    assert monitoring.get_resource_utilization()["status"] == "error"
    assert logging_tools.get_recent_errors()["status"] == "error"
