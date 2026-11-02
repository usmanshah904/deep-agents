"""Propose -> approve -> apply, with a fake cloud (no floci needed)."""

import pytest

from sre_mcp.changes import manager, resources
from sre_mcp.observability import client


@pytest.fixture
def cloud(monkeypatch, tmp_path):
    vms = {
        "web-vm-1": {"name": "web-vm-1", "zone": "us-central1-a", "machine_type": "n2-standard-8", "status": "RUNNING"},
        "legacy-ftp": {"name": "legacy-ftp", "zone": "us-central1-c", "machine_type": "e2-standard-2", "status": "TERMINATED"},
    }
    buckets = {"logs": {"name": "logs", "storage_class": "STANDARD", "lifecycle_rules": []}}
    writes = []

    def stop(vm):
        writes.append(("stop", vm["name"])); vms[vm["name"]]["status"] = "TERMINATED"; return vms[vm["name"]]

    def start(vm):
        writes.append(("start", vm["name"])); vms[vm["name"]]["status"] = "RUNNING"; return vms[vm["name"]]

    def set_type(vm, mt):
        writes.append(("resize", vm["name"], mt)); vms[vm["name"]]["machine_type"] = mt; return vms[vm["name"]]

    def patch_bucket(name, body):
        writes.append(("patch", name, body))
        b = buckets[name]
        if "storageClass" in body:
            b["storage_class"] = body["storageClass"]
        if "lifecycle" in body:
            b["lifecycle_rules"] = body["lifecycle"]["rule"]
        return dict(b)

    monkeypatch.setenv("CHANGES_FILE", str(tmp_path / "changes.jsonl"))
    monkeypatch.setattr(client, "is_local", lambda: True)
    monkeypatch.setattr(resources, "find_vm", lambda n: dict(vms[n]) if n in vms else None)
    monkeypatch.setattr(resources, "list_vms", lambda: [dict(v) for v in vms.values()])
    monkeypatch.setattr(resources, "machine_types", lambda zone: ["e2-standard-2", "n2-standard-4", "n2-standard-8"])
    monkeypatch.setattr(resources, "find_bucket", lambda n: dict(buckets[n]) if n in buckets else None)
    monkeypatch.setattr(resources, "list_buckets", lambda: [dict(b) for b in buckets.values()])
    monkeypatch.setattr(resources, "stop_vm", stop)
    monkeypatch.setattr(resources, "start_vm", start)
    monkeypatch.setattr(resources, "set_machine_type", set_type)
    monkeypatch.setattr(resources, "patch_bucket", patch_bucket)
    monkeypatch.setattr(resources, "audit_log", lambda *a, **k: writes.append(("audit",)))
    return {"vms": vms, "buckets": buckets, "writes": writes}


def test_propose_changes_nothing(cloud):
    r = manager.propose_change("resize_vm", "web-vm-1", machine_type="n2-standard-4", reason="oversized")
    c = r["change"]
    assert r["status"] == "ok" and c["status"] == "proposed" and c["id"].startswith("chg-")
    assert c["before"]["machine_type"] == "n2-standard-8" and c["after"]["machine_type"] == "n2-standard-4"
    assert cloud["writes"] == [] and cloud["vms"]["web-vm-1"]["machine_type"] == "n2-standard-8"
    assert "approve" in r["next_step"]


def test_apply_resizes_running_vm_with_stop_and_start(cloud):
    cid = manager.propose_change("resize_vm", "web-vm-1", machine_type="n2-standard-4")["change"]["id"]
    r = manager.apply_change(cid)
    assert r["status"] == "ok" and r["change"]["status"] == "applied"
    assert [w[0] for w in cloud["writes"]] == ["stop", "resize", "start", "audit"]
    assert cloud["vms"]["web-vm-1"] == {**cloud["vms"]["web-vm-1"], "machine_type": "n2-standard-4", "status": "RUNNING"}


def test_apply_only_once_and_only_known_ids(cloud):
    cid = manager.propose_change("start_vm", "legacy-ftp")["change"]["id"]
    assert manager.apply_change(cid)["status"] == "ok"
    assert "not 'proposed'" in manager.apply_change(cid)["message"]
    assert manager.apply_change("chg-000000")["status"] == "error"


def test_cancelled_change_cannot_be_applied(cloud):
    cid = manager.propose_change("set_bucket_storage_class", "logs", storage_class="COLDLINE")["change"]["id"]
    assert manager.cancel_change(cid)["change"]["status"] == "cancelled"
    assert manager.apply_change(cid)["status"] == "error"
    assert cloud["writes"] == [] and cloud["buckets"]["logs"]["storage_class"] == "STANDARD"


def test_expired_change_cannot_be_applied(cloud, monkeypatch):
    cid = manager.propose_change("set_bucket_storage_class", "logs", storage_class="NEARLINE")["change"]["id"]
    later = manager._now() + manager.timedelta(minutes=manager.EXPIRY_MINUTES + 1)
    monkeypatch.setattr(manager, "_now", lambda: later)
    assert "expired" in manager.apply_change(cid)["message"]
    assert cloud["writes"] == []
    assert manager.list_changes()["counts"] == {"expired": 1}


def test_bucket_lifecycle_rule_is_added(cloud):
    cid = manager.propose_change("add_bucket_lifecycle_rule", "logs", storage_class="ARCHIVE", age_days=365)["change"]["id"]
    r = manager.apply_change(cid)
    assert r["change"]["result"]["lifecycle_rules"] == [{"action": {"type": "SetStorageClass", "storageClass": "ARCHIVE"}, "condition": {"age": 365}}]


@pytest.mark.parametrize("args, message", [
    (("delete_vm", "web-vm-1"), "Unknown action"),
    (("resize_vm", "nope"), "No VM named"),
    (("resize_vm", "web-vm-1", "m1-mega"), "machine_type must be one of"),
    (("resize_vm", "web-vm-1", "n2-standard-8"), "already uses"),
    (("stop_vm", "legacy-ftp"), "not running"),
    (("restart_vm", "legacy-ftp"), "Use start_vm"),
])
def test_invalid_proposals_are_refused(cloud, args, message):
    r = manager.propose_change(*args)
    assert r["status"] == "error" and message in r["message"]
    assert cloud["writes"] == []


def test_bad_bucket_values_are_refused(cloud):
    assert "storage_class must be" in manager.propose_change("set_bucket_storage_class", "logs", storage_class="HOT")["message"]
    assert "age_days" in manager.propose_change("add_bucket_lifecycle_rule", "logs", storage_class="ARCHIVE", age_days=0)["message"]


def test_writes_refused_outside_local_emulator(cloud, monkeypatch):
    cid = manager.propose_change("start_vm", "legacy-ftp")["change"]["id"]
    monkeypatch.setattr(client, "is_local", lambda: False)
    assert "local floci-gcp" in manager.apply_change(cid)["message"]
    assert "local floci-gcp" in manager.propose_change("start_vm", "legacy-ftp")["message"]
    assert cloud["writes"] == []


def test_history_lists_newest_first_with_counts(cloud):
    a = manager.propose_change("start_vm", "legacy-ftp")["change"]["id"]
    manager.apply_change(a)
    b = manager.propose_change("set_bucket_storage_class", "logs", storage_class="COLDLINE")["change"]["id"]
    h = manager.list_changes()
    assert h["counts"] == {"applied": 1, "proposed": 1}
    assert {c["id"] for c in h["changes"]} == {a, b}


def test_never_expires_when_setting_is_zero(cloud, monkeypatch):
    monkeypatch.setenv("CHANGE_EXPIRY_MINUTES", "0")
    r = manager.propose_change("start_vm", "legacy-ftp")
    assert r["change"]["expires_at"] is None and "does not expire" in r["next_step"]
    much_later = manager._now() + manager.timedelta(days=365)
    monkeypatch.setattr(manager, "_now", lambda: much_later)
    assert manager.list_changes()["counts"] == {"proposed": 1}
    assert manager.apply_change(r["change"]["id"])["status"] == "ok"


def test_change_refused_when_resource_changed_since_proposal(cloud):
    cid = manager.propose_change("resize_vm", "web-vm-1", machine_type="n2-standard-4")["change"]["id"]
    cloud["vms"]["web-vm-1"]["machine_type"] = "e2-standard-2"  # someone resized it meanwhile
    r = manager.apply_change(cid)
    assert r["status"] == "error" and "changed since it was proposed" in r["message"]
    assert cloud["writes"] == []
    assert manager.list_changes()["counts"] == {"proposed": 1}  # still waiting: the user can cancel it


def test_restart_refused_when_vm_was_stopped_meanwhile(cloud):
    cid = manager.propose_change("restart_vm", "web-vm-1")["change"]["id"]
    cloud["vms"]["web-vm-1"]["status"] = "TERMINATED"
    r = manager.apply_change(cid)
    assert r["status"] == "error" and "not applied" in r["message"]
    assert cloud["writes"] == []
