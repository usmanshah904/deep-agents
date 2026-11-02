"""Simulates the db-proxy incident being fixed, so you can watch the dashboard recover.

Writes healthy data to floci-gcp with the current time:
- db-proxy CPU back to normal (three points over the last 10 minutes)
- NOTICE logs starting with "RESOLVED:" for db-proxy and payments-api
- a few normal payments-api INFO logs

Nothing is deleted: the old errors stay in the logs, like in real GCP. The
dashboard shows the incident as resolved, and the errors leave the time window
as they age (fastest on the 1h view).

Only runs against a local emulator (localhost). Run: python -m seed.simulate_fix
"""

import os
import random
import sys
from datetime import datetime, timedelta, timezone

from sre_mcp.observability import client
from seed.seed_floci import _entry, _k8s, _vm


def write_cpu(rng: random.Random, now: datetime) -> int:
    for minutes_ago in (10, 5, 0):
        when = client.to_rfc3339(now - timedelta(minutes=minutes_ago))
        cpu = rng.uniform(0.38, 0.46)
        client.post(f"/v3/projects/{client.project()}/timeSeries", {"timeSeries": [{
            "metric": {"type": "compute.googleapis.com/instance/cpu/utilization", "labels": {"instance_name": "db-proxy"}},
            "resource": {"type": "gce_instance", "labels": {"project_id": client.project(), "zone": "us-central1-a", "instance_id": "db-proxy"}},
            "points": [{"interval": {"endTime": when}, "value": {"doubleValue": round(cpu, 4)}}],
        }]})
    return 3


def write_logs(now: datetime) -> int:
    db_proxy = _vm("db-proxy", "us-central1-a")
    payments = _k8s("prod-cluster", "checkout", "payments-api")
    entries = [
        _entry(db_proxy, "syslog", "NOTICE", "RESOLVED: Connection pool back to normal (38/200 connections in use)", now - timedelta(minutes=9)),
        _entry(payments, "payments-api", "NOTICE", "RESOLVED: Connected to db-proxy:5432 again, no more timeouts", now - timedelta(minutes=8)),
    ] + [
        _entry(payments, "payments-api", "INFO", "Payment processed", now - timedelta(minutes=m)) for m in (7, 5, 3, 2, 1)
    ]
    client.post("/v2/entries:write", {"entries": entries})
    return len(entries)


def simulate_recovery() -> tuple[int, int]:
    """Writes the healthy metrics and recovery logs. Returns (metric points, log entries)."""
    now = datetime.now(timezone.utc).replace(microsecond=0)
    return write_cpu(random.Random(), now), write_logs(now)


def main() -> None:
    url = os.getenv("OBS_API_URL", client.DEFAULT_URL)
    if "localhost" not in url and "127.0.0.1" not in url:
        sys.exit(f"Refusing to write to {url}: this simulation is only for the local floci-gcp emulator.")
    try:
        points, logs = simulate_recovery()
    except client.ApiError as exc:
        sys.exit(str(exc))
    print(f"Simulated fix in '{client.project()}': {points} healthy db-proxy CPU points, {logs} recovery log entries.")


if __name__ == "__main__":
    main()
