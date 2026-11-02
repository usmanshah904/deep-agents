"""Reads and changes Compute Engine VMs and Cloud Storage buckets through the REST API."""

import os
import time
from datetime import datetime, timezone

from ..observability import client

STORAGE_CLASSES = ["STANDARD", "NEARLINE", "COLDLINE", "ARCHIVE"]


def zones() -> list[str]:
    return [z.strip() for z in os.getenv("GCP_ZONES", "us-central1-a,us-central1-b,us-central1-c").split(",") if z.strip()]


def _compute(path: str) -> str:
    return f"/compute/v1/projects/{client.project()}{path}"


def _last(url: str) -> str:
    return url.rsplit("/", 1)[-1] if url else ""


def list_vms() -> list[dict]:
    vms = []
    for zone in zones():
        for vm in client.get(_compute(f"/zones/{zone}/instances")).get("items", []):
            vms.append({"name": vm["name"], "zone": zone, "machine_type": _last(vm.get("machineType", "")), "status": vm.get("status", "")})
    return sorted(vms, key=lambda v: v["name"])


def find_vm(name: str) -> dict | None:
    return next((v for v in list_vms() if v["name"] == name), None)


def machine_types(zone: str) -> list[str]:
    return sorted(m["name"] for m in client.get(_compute(f"/zones/{zone}/machineTypes")).get("items", []))


def _wait_for_status(name: str, want: str, timeout: float = 60) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        vm = find_vm(name)
        if vm and vm["status"] == want:
            return vm
        if time.monotonic() > deadline:
            raise client.ApiError(f"{name} did not reach {want} within {timeout:.0f}s (now {vm and vm['status']}).")
        time.sleep(1)


def stop_vm(vm: dict) -> dict:
    client.post(_compute(f"/zones/{vm['zone']}/instances/{vm['name']}/stop"), {})
    return _wait_for_status(vm["name"], "TERMINATED")


def start_vm(vm: dict) -> dict:
    client.post(_compute(f"/zones/{vm['zone']}/instances/{vm['name']}/start"), {})
    return _wait_for_status(vm["name"], "RUNNING")


def set_machine_type(vm: dict, machine_type: str) -> dict:
    client.post(
        _compute(f"/zones/{vm['zone']}/instances/{vm['name']}/setMachineType"),
        {"machineType": f"zones/{vm['zone']}/machineTypes/{machine_type}"},
    )
    return find_vm(vm["name"])


def _bucket_view(b: dict) -> dict:
    return {
        "name": b["name"],
        "storage_class": b.get("storageClass", "STANDARD"),
        "lifecycle_rules": (b.get("lifecycle") or {}).get("rule", []),
    }


def list_buckets() -> list[dict]:
    items = client.get("/storage/v1/b", {"project": client.project()}).get("items", [])
    return sorted((_bucket_view(b) for b in items), key=lambda b: b["name"])


def find_bucket(name: str) -> dict | None:
    return next((b for b in list_buckets() if b["name"] == name), None)


def patch_bucket(name: str, body: dict) -> dict:
    return _bucket_view(client.patch(f"/storage/v1/b/{name}", body))


def audit_log(message: str, resource: dict, severity: str = "NOTICE") -> None:
    """Records an applied change in Cloud Logging (log name: changes)."""
    client.post("/v2/entries:write", {"entries": [{
        "logName": f"projects/{client.project()}/logs/changes",
        "resource": resource,
        "severity": severity,
        "textPayload": message,
        "timestamp": client.to_rfc3339(datetime.now(timezone.utc)),
    }]})


def vm_resource(vm: dict) -> dict:
    return {"type": "gce_instance", "labels": {"project_id": client.project(), "zone": vm["zone"], "instance_id": vm["name"], "instance_name": vm["name"]}}


def bucket_resource(name: str) -> dict:
    return {"type": "gcs_bucket", "labels": {"project_id": client.project(), "bucket_name": name}}
