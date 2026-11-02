"""Fills floci-gcp with sample resources, metrics and logs for the last 24 hours.

VM, bucket and GKE names come from the cost tools' mock data, so costs and
usage match. The VMs and buckets are created as real floci resources, so the
agent can propose changes to them.
Story in the data: db-proxy CPU spikes in the last 3 hours, payments-api
then times out talking to it, and db-proxy runs out of connections.

Only runs against a local emulator (localhost). Run: python -m seed.seed_floci
"""

import json
import math
import os
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sre_mcp.observability import client

MOCK_DIR = Path(__file__).resolve().parent.parent / "sre_mcp" / "cost" / "data" / "mock"
HOURS = 24
INCIDENT_HOURS = 3  # db-proxy incident in the last 3 hours
NOW = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)


def _load(name: str) -> dict:
    return json.loads((MOCK_DIR / name).read_text())


def _vm_series(vm: dict, metric_type: str, value: float) -> dict:
    return {
        "metric": {"type": metric_type, "labels": {"instance_name": vm["name"]}},
        "resource": {
            "type": "gce_instance",
            "labels": {"project_id": client.project(), "zone": vm["zone"], "instance_id": vm["name"]},
        },
        "value": value,
    }


def _gke_series(w: dict, metric_type: str, value: float) -> dict:
    return {
        "metric": {"type": metric_type},
        "resource": {
            "type": "k8s_container",
            "labels": {
                "project_id": client.project(),
                "location": "us-central1",
                "cluster_name": w["cluster"],
                "namespace_name": w["namespace"],
                "container_name": w["workload"],
            },
        },
        "value": value,
    }


def _wave(base: float, hour: int, rng: random.Random) -> float:
    """Daily pattern plus noise around a base percentage."""
    return max(0.5, base * (1 + 0.15 * math.sin(hour / 24 * 2 * math.pi)) + rng.uniform(-2, 2))


def seed_metrics(rng: random.Random) -> int:
    vms = _load("compute.json")["instances"]
    workloads = _load("gke.json")["workloads"]
    written = 0
    for h in range(HOURS, 0, -1):
        end = client.to_rfc3339(NOW - timedelta(hours=h - 1))
        incident = h <= INCIDENT_HOURS + 1  # covers the hour the first errors appear in
        series = []
        for vm in vms:
            cpu = _wave(vm["cpu_util_pct"], h, rng)
            if vm["name"] == "db-proxy" and incident:
                cpu = rng.uniform(90, 97)
            mem = _wave(vm["mem_util_pct"], h, rng)
            series.append(_vm_series(vm, "compute.googleapis.com/instance/cpu/utilization", min(cpu, 100) / 100))
            series.append(_vm_series(vm, "agent.googleapis.com/memory/percent_used", min(mem, 100)))
        for w in workloads:
            cpu = _wave(w["cpu_used"] / w["cpu_requested"] * 100, h, rng)
            mem = _wave(w["mem_used_gb"] / w["mem_requested_gb"] * 100, h, rng)
            series.append(_gke_series(w, "kubernetes.io/container/cpu/request_utilization", cpu / 100))
            series.append(_gke_series(w, "kubernetes.io/container/memory/request_utilization", mem / 100))
        body = {
            "timeSeries": [
                {
                    "metric": s["metric"],
                    "resource": s["resource"],
                    "points": [{"interval": {"endTime": end}, "value": {"doubleValue": round(s["value"], 4)}}],
                }
                for s in series
            ]
        }
        client.post(f"/v3/projects/{client.project()}/timeSeries", body)
        written += len(series)
    return written


def _k8s(cluster: str, namespace: str, container: str) -> dict:
    return {
        "type": "k8s_container",
        "labels": {
            "project_id": client.project(),
            "location": "us-central1",
            "cluster_name": cluster,
            "namespace_name": namespace,
            "container_name": container,
        },
    }


def _vm(name: str, zone: str) -> dict:
    return {"type": "gce_instance", "labels": {"project_id": client.project(), "zone": zone, "instance_id": name, "instance_name": name}}


def _entry(resource: dict, log: str, severity: str, message: str, when: datetime) -> dict:
    return {
        "logName": f"projects/{client.project()}/logs/{log}",
        "resource": resource,
        "severity": severity,
        "textPayload": message,
        "timestamp": client.to_rfc3339(when),
    }


def _times(rng: random.Random, count: int, hours: float) -> list[datetime]:
    return [NOW - timedelta(minutes=rng.uniform(1, hours * 60)) for _ in range(count)]


def seed_logs(rng: random.Random) -> int:
    payments = _k8s("prod-cluster", "checkout", "payments-api")
    cart = _k8s("prod-cluster", "checkout", "cart-service")
    search = _k8s("prod-cluster", "search", "search-indexer")
    frontend = _k8s("prod-cluster", "web", "frontend")
    etl = _k8s("prod-cluster", "data", "batch-etl")
    db_proxy = _vm("db-proxy", "us-central1-a")
    web_vm = _vm("web-vm-1", "us-central1-a")

    plan = [
        # (resource, log, severity, message, count, within last N hours)
        (payments, "payments-api", "ERROR", "Timeout connecting to db-proxy:5432 after 30s", 24, INCIDENT_HOURS),
        (payments, "payments-api", "WARNING", "Retrying payment request (attempt 2/3)", 15, INCIDENT_HOURS),
        (payments, "payments-api", "INFO", "Payment processed", 40, HOURS),
        (db_proxy, "syslog", "CRITICAL", "Connection pool exhausted (max 200 connections)", 3, INCIDENT_HOURS),
        (db_proxy, "syslog", "WARNING", "High CPU load on db-proxy", 6, INCIDENT_HOURS),
        (cart, "cart-service", "INFO", "Cart updated", 30, HOURS),
        (search, "search-indexer", "ERROR", "Index shard 3 missing, rebuilding", 6, HOURS),
        (search, "search-indexer", "INFO", "Indexed batch of 500 documents", 20, HOURS),
        (frontend, "frontend", "WARNING", "Slow upstream response from cart-service (2.4s)", 10, HOURS),
        (frontend, "frontend", "INFO", "GET /checkout 200", 40, HOURS),
        (etl, "batch-etl", "INFO", "ETL job finished", 4, HOURS),
        (web_vm, "syslog", "INFO", "nginx reloaded", 2, HOURS),
    ]
    entries = [
        _entry(res, log, sev, msg, when)
        for res, log, sev, msg, count, hours in plan
        for when in _times(rng, count, hours)
    ]
    client.post("/v2/entries:write", {"entries": entries})
    return len(entries)


# floci's machine type catalog is small; mock types it lacks map to the closest one.
MACHINE_TYPE_FALLBACK = {"e2-standard-4": "n2-standard-4", "n2-highmem-8": "n2-standard-8"}
NETWORK, SUBNET, REGION = "sre-net", "sre-subnet", "us-central1"


def _create(path: str, body: dict) -> bool:
    """Creates a resource. Returns False if it already exists, so seeding can be re-run."""
    try:
        client.post(path, body)
        return True
    except client.ApiError as exc:
        if exc.status == 409:
            return False
        raise


def seed_resources() -> tuple[int, int]:
    """Creates the mock VMs (with network, subnet and boot disks) and buckets."""
    compute = f"/compute/v1/projects/{client.project()}"
    _create(f"{compute}/global/networks", {"name": NETWORK, "autoCreateSubnetworks": False})
    _create(f"{compute}/regions/{REGION}/subnetworks", {"name": SUBNET, "network": f"global/networks/{NETWORK}", "ipCidrRange": "10.10.0.0/24"})
    vms = 0
    for vm in _load("compute.json")["instances"]:
        zone, name = vm["zone"], vm["name"]
        machine_type = MACHINE_TYPE_FALLBACK.get(vm["machine_type"], vm["machine_type"])
        _create(f"{compute}/zones/{zone}/disks", {"name": f"{name}-boot", "sizeGb": "20"})
        vms += _create(f"{compute}/zones/{zone}/instances", {
            "name": name,
            "machineType": f"zones/{zone}/machineTypes/{machine_type}",
            "labels": {"env": vm["env"], "project": vm["project"]},
            "networkInterfaces": [{"network": f"global/networks/{NETWORK}", "subnetwork": f"regions/{REGION}/subnetworks/{SUBNET}"}],
            "disks": [{"boot": True, "source": f"zones/{zone}/disks/{name}-boot"}],
        })
    buckets = 0
    for b in _load("storage.json")["buckets"]:
        buckets += _create(f"/storage/v1/b?project={client.project()}", {"name": b["name"], "storageClass": b["storage_class"], "location": "US"})
    return vms, buckets


def main() -> None:
    url = os.getenv("OBS_API_URL", client.DEFAULT_URL)
    if "localhost" not in url and "127.0.0.1" not in url:
        sys.exit(f"Refusing to seed {url}: seeding is only for the local floci-gcp emulator.")
    rng = random.Random(42)
    try:
        vms, buckets = seed_resources()
        points = seed_metrics(rng)
        logs = seed_logs(rng)
    except client.ApiError as exc:
        sys.exit(str(exc))
    print(f"Seeded project '{client.project()}': {vms} new VMs, {buckets} new buckets, {points} metric points, {logs} log entries.")


if __name__ == "__main__":
    main()
