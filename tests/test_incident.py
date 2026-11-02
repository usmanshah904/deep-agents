"""check_incident_status, with the Logging and Monitoring APIs faked (no floci needed)."""

from datetime import datetime, timedelta, timezone

import pytest

from sre_mcp.observability import client, incident


def _ago(minutes: float) -> str:
    return client.to_rfc3339(datetime.now(timezone.utc) - timedelta(minutes=minutes))


def _cpu(points):
    """points: [(minutes_ago, cpu_fraction)]"""
    return {"metric": {"type": "compute.googleapis.com/instance/cpu/utilization", "labels": {"instance_name": "db-proxy"}},
            "resource": {"type": "gce_instance", "labels": {"instance_id": "db-proxy"}},
            "points": [{"interval": {"endTime": _ago(m)}, "value": {"doubleValue": v}} for m, v in points]}


def _error(minutes_ago):
    return {"logName": "projects/demo-project/logs/syslog", "severity": "ERROR", "textPayload": "pool exhausted",
            "resource": {"type": "gce_instance", "labels": {"instance_name": "db-proxy"}}, "timestamp": _ago(minutes_ago)}


@pytest.fixture
def api(monkeypatch):
    state = {"logs": [], "series": []}
    monkeypatch.setattr(client, "post", lambda path, body, timeout=20: {"entries": state["logs"]})
    monkeypatch.setattr(client, "get", lambda path, params=None: {"timeSeries": state["series"]})
    return state


def test_high_cpu_is_ongoing(api):
    api["logs"] = [_error(50)]
    api["series"] = [_cpu([(120, 0.5), (60, 0.95)])]
    assert incident.check_incident_status("db-proxy")["verdict"] == "ongoing"


def test_old_errors_after_recovery_are_resolved(api):
    # Errors stay in the logs, but they all happened before CPU came back to normal.
    api["logs"] = [_error(12), _error(30)]
    api["series"] = [_cpu([(60, 0.95), (10, 0.4), (5, 0.42), (0, 0.41)])]
    r = incident.check_incident_status("db-proxy")
    assert r["verdict"] == "resolved" and r["errors_in_window"] == 2 and r["cpu"]["latest_pct"] == 41.0


def test_errors_after_recovery_are_recovering(api):
    api["logs"] = [_error(3)]
    api["series"] = [_cpu([(60, 0.95), (10, 0.4), (0, 0.41)])]
    assert incident.check_incident_status("db-proxy")["verdict"] == "recovering"


def test_quiet_for_long_enough_is_resolved(api):
    api["logs"] = [_error(40)]
    api["series"] = [_cpu([(30, 0.4), (0, 0.41)])]
    assert incident.check_incident_status("db-proxy")["verdict"] == "resolved"


def test_no_errors_and_workload_name_match(api):
    assert incident.check_incident_status("db-proxy")["verdict"] == "no_errors"
    api["logs"] = [{**_error(2), "resource": {"type": "k8s_container", "labels": {
        "cluster_name": "prod-cluster", "namespace_name": "checkout", "container_name": "payments-api"}}}]
    r = incident.check_incident_status("payments-api")
    assert r["verdict"] == "ongoing" and r["cpu"] is None


def test_api_down_is_an_error(monkeypatch):
    def down(*args, **kwargs):
        raise client.ApiError("Cannot reach http://localhost:4588")
    monkeypatch.setattr(client, "post", down)
    assert incident.check_incident_status("db-proxy")["status"] == "error"
