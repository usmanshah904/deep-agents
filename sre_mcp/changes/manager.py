"""Propose -> approve -> apply.

propose_change only reads and records a plan. apply_change runs a proposed
change, and is meant to be called only after the user approves that exact
change ID in chat (agent rule, plus the approval pause in agent.py).
Every step is appended to changes.jsonl. Writes are allowed only on a local
emulator (floci-gcp). No action deletes anything.
"""

import json
import os
import secrets
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..observability import client

from . import resources

EXPIRY_MINUTES = 15  # default; CHANGE_EXPIRY_MINUTES overrides it, 0 = never expires
_apply_lock = threading.Lock()

ACTIONS = {
    "resize_vm": "Change a VM's machine type (stops and starts the VM). Needs machine_type.",
    "stop_vm": "Stop a running VM.",
    "start_vm": "Start a stopped VM.",
    "restart_vm": "Stop and start a VM.",
    "set_bucket_storage_class": "Change a bucket's default storage class. Needs storage_class.",
    "add_bucket_lifecycle_rule": "Add a rule that moves objects older than age_days to storage_class.",
}


def _store() -> Path:
    return Path(os.getenv("CHANGES_FILE", Path(__file__).resolve().parents[2] / "data" / "changes.jsonl"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _append(event: dict) -> None:
    path = _store()
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")


def _all_changes() -> dict[str, dict]:
    """Latest state of every change, built from the event log."""
    changes: dict[str, dict] = {}
    path = _store()
    if not path.exists():
        return changes
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            e = json.loads(line)
            changes.setdefault(e["id"], {}).update(e)
    return changes


def _record(change: dict, status: str, **fields) -> dict:
    change = {**change, **fields, "status": status, f"{status}_at": _iso(_now())}
    _append({"id": change["id"], "status": status, f"{status}_at": change[f"{status}_at"], **fields})
    return change


def _error(message: str) -> dict:
    return {"status": "error", "message": message}


def _expiry_minutes() -> int:
    return int(os.getenv("CHANGE_EXPIRY_MINUTES", str(EXPIRY_MINUTES)))


def _is_expired(change: dict, now: str) -> bool:
    return bool(change.get("expires_at")) and now > change["expires_at"]


def _plan(action: str, target: str, machine_type: str | None, storage_class: str | None, age_days: int | None) -> dict:
    """Validates the request and reads the current state. Changes nothing."""
    if action in ("resize_vm", "stop_vm", "start_vm", "restart_vm"):
        vm = resources.find_vm(target)
        if not vm:
            raise ValueError(f"No VM named '{target}'. Use get_inventory to see VM names.")
        before = {"machine_type": vm["machine_type"], "status": vm["status"]}
        if action == "resize_vm":
            allowed = resources.machine_types(vm["zone"])
            if machine_type not in allowed:
                raise ValueError(f"machine_type must be one of {', '.join(allowed)}.")
            if machine_type == vm["machine_type"]:
                raise ValueError(f"{target} already uses {machine_type}.")
            return {"before": before, "after": {**before, "machine_type": machine_type},
                    "summary": f"Resize VM {target} from {vm['machine_type']} to {machine_type}",
                    "risk": "The VM is stopped, resized and started again: about a minute of downtime."}
        if action == "stop_vm":
            if vm["status"] != "RUNNING":
                raise ValueError(f"{target} is not running (status {vm['status']}).")
            return {"before": before, "after": {**before, "status": "TERMINATED"},
                    "summary": f"Stop VM {target}", "risk": "Anything running on the VM is unavailable until it is started again."}
        if action == "start_vm":
            if vm["status"] != "TERMINATED":
                raise ValueError(f"{target} is not stopped (status {vm['status']}).")
            return {"before": before, "after": {**before, "status": "RUNNING"},
                    "summary": f"Start VM {target}", "risk": "Low. The VM starts billing again while it runs."}
        if vm["status"] != "RUNNING":
            raise ValueError(f"{target} is not running (status {vm['status']}). Use start_vm.")
        return {"before": before, "after": before,
                "summary": f"Restart VM {target}", "risk": "Brief downtime while the VM stops and starts."}

    if action in ("set_bucket_storage_class", "add_bucket_lifecycle_rule"):
        bucket = resources.find_bucket(target)
        if not bucket:
            raise ValueError(f"No bucket named '{target}'. Use get_inventory to see bucket names.")
        if storage_class not in resources.STORAGE_CLASSES:
            raise ValueError(f"storage_class must be one of {', '.join(resources.STORAGE_CLASSES)}.")
        before = {"storage_class": bucket["storage_class"], "lifecycle_rules": bucket["lifecycle_rules"]}
        if action == "set_bucket_storage_class":
            if storage_class == bucket["storage_class"]:
                raise ValueError(f"{target} already uses {storage_class}.")
            return {"before": before, "after": {**before, "storage_class": storage_class},
                    "summary": f"Change bucket {target} default storage class from {bucket['storage_class']} to {storage_class}",
                    "risk": "Applies to new objects. Colder classes have retrieval fees and minimum storage durations."}
        if not isinstance(age_days, int) or not 1 <= age_days <= 3650:
            raise ValueError("age_days must be a whole number from 1 to 3650.")
        rule = {"action": {"type": "SetStorageClass", "storageClass": storage_class}, "condition": {"age": age_days}}
        if rule in bucket["lifecycle_rules"]:
            raise ValueError(f"{target} already has this rule.")
        return {"before": before, "after": {**before, "lifecycle_rules": bucket["lifecycle_rules"] + [rule]},
                "summary": f"Add a lifecycle rule to {target}: move objects older than {age_days} days to {storage_class}",
                "risk": "Objects move automatically. Reading them back from a colder class costs retrieval fees."}

    raise ValueError(f"Unknown action '{action}'. Allowed: {', '.join(ACTIONS)}.")


def get_inventory() -> dict:
    """Live list of the VMs and buckets the agent can change, and the allowed values."""
    try:
        vms = resources.list_vms()
        buckets = resources.list_buckets()
        types = resources.machine_types(resources.zones()[0])
    except client.ApiError as exc:
        return _error(str(exc))
    return {
        "status": "ok",
        "project": client.project(),
        "vms": vms,
        "buckets": buckets,
        "machine_types": types,
        "storage_classes": resources.STORAGE_CLASSES,
        "actions": ACTIONS,
        "writes_allowed": client.is_local(),
    }


def propose_change(
    action: str,
    target: str,
    machine_type: str | None = None,
    storage_class: str | None = None,
    age_days: int | None = None,
    reason: str = "",
) -> dict:
    """Plans one change and records it as 'proposed'. Changes NOTHING.

    action: resize_vm, stop_vm, start_vm, restart_vm, set_bucket_storage_class
    or add_bucket_lifecycle_rule. target: VM or bucket name. reason: why
    (for example the cost or incident finding). After this, show the user the
    change ID, summary, before/after and risk, and wait for their approval.
    """
    if not client.is_local():
        return _error("Changes are only allowed on the local floci-gcp emulator for now.")
    try:
        plan = _plan(action, target, machine_type, storage_class, age_days)
    except ValueError as exc:
        return _error(str(exc))
    except client.ApiError as exc:
        return _error(str(exc))
    now = _now()
    minutes = _expiry_minutes()
    change = {
        "id": "chg-" + secrets.token_hex(3),
        "action": action,
        "target": target,
        "params": {k: v for k, v in {"machine_type": machine_type, "storage_class": storage_class, "age_days": age_days}.items() if v is not None},
        "reason": reason,
        **plan,
        "expires_at": _iso(now + timedelta(minutes=minutes)) if minutes > 0 else None,
    }
    change = _record(change, "proposed", **{k: v for k, v in change.items() if k != "id"})
    return {
        "status": "ok",
        "change": change,
        "next_step": f"Nothing has changed. Show this to the user and ask them to approve {change['id']}. "
                     f"Call apply_change only after they say yes to {change['id']}. "
                     + (f"It expires in {minutes} minutes." if minutes > 0 else "It does not expire: it waits until it is approved or cancelled."),
    }


def _execute(change: dict) -> dict:
    action, target, params = change["action"], change["target"], change["params"]
    note = None
    if action in ("resize_vm", "stop_vm", "start_vm", "restart_vm"):
        vm = resources.find_vm(target)
        if action == "resize_vm":
            was_running = vm["status"] == "RUNNING"
            if was_running:
                resources.stop_vm(vm)
            resources.set_machine_type(vm, params["machine_type"])
            if was_running:
                resources.start_vm(vm)
        elif action == "stop_vm":
            resources.stop_vm(vm)
        elif action == "start_vm":
            resources.start_vm(vm)
        else:
            resources.stop_vm(vm)
            resources.start_vm(vm)
            if target == "db-proxy":
                # floci runs no real workload, so the effect of the restart is simulated.
                from seed.simulate_fix import simulate_recovery
                simulate_recovery()
                note = "Simulated effect: floci has no real workload, so healthy db-proxy metrics and RESOLVED logs were written to show the recovery."
        vm = resources.find_vm(target)
        resources.audit_log(f"CHANGE APPLIED {change['id']}: {change['summary']}", resources.vm_resource(vm))
        return {"after": {"machine_type": vm["machine_type"], "status": vm["status"]}, "note": note}

    if action == "set_bucket_storage_class":
        bucket = resources.patch_bucket(target, {"storageClass": params["storage_class"]})
    else:
        current = resources.find_bucket(target)["lifecycle_rules"]
        rule = {"action": {"type": "SetStorageClass", "storageClass": params["storage_class"]}, "condition": {"age": params["age_days"]}}
        bucket = resources.patch_bucket(target, {"lifecycle": {"rule": current + [rule]}})
    resources.audit_log(f"CHANGE APPLIED {change['id']}: {change['summary']}", resources.bucket_resource(target))
    return {"after": {"storage_class": bucket["storage_class"], "lifecycle_rules": bucket["lifecycle_rules"]}, "note": note}


def apply_change(change_id: str) -> dict:
    """Applies ONE proposed change. Only call this after the user has explicitly
    approved this exact change ID in chat. Refuses expired, cancelled or already
    applied changes, and changes whose resource is no longer in the 'before' state."""
    if not client.is_local():
        return _error("Changes are only allowed on the local floci-gcp emulator for now.")
    with _apply_lock:
        change = _all_changes().get(change_id)
        if not change:
            return _error(f"No change with ID '{change_id}'. Propose it first with propose_change.")
        if change["status"] != "proposed":
            return _error(f"{change_id} is '{change['status']}', not 'proposed'. Only proposed changes can be applied.")
        if _is_expired(change, _iso(_now())):
            _record(change, "expired")
            return _error(f"{change_id} expired at {change['expires_at']}. Propose it again.")
        # Hard check: the resource must still be exactly as it was when the change was proposed.
        params = change.get("params", {})
        try:
            now_before = _plan(change["action"], change["target"], params.get("machine_type"),
                               params.get("storage_class"), params.get("age_days"))["before"]
        except ValueError as exc:
            return _error(f"{change_id} was not applied: {exc} The resource changed since it was proposed. "
                          "Cancel it, and propose a new change if one is still needed.")
        except client.ApiError as exc:
            return _error(str(exc))
        if now_before != change["before"]:
            return _error(f"{change_id} was not applied: {change['target']} changed since it was proposed "
                          f"(then: {change['before']}, now: {now_before}). "
                          "Cancel it, and propose a new change if one is still needed.")
        try:
            result = _execute(change)
        except (client.ApiError, KeyError, TypeError) as exc:
            failed = _record(change, "failed", error=str(exc))
            return {"status": "error", "message": f"Applying {change_id} failed: {exc}", "change": failed}
        applied = _record(change, "applied", result=result["after"], note=result["note"])
    return {"status": "ok", "change": applied, "message": f"{change_id} applied: {change['summary']}."}


def cancel_change(change_id: str) -> dict:
    """Cancels a proposed change, for example when the user says no."""
    change = _all_changes().get(change_id)
    if not change:
        return _error(f"No change with ID '{change_id}'.")
    if change["status"] != "proposed":
        return _error(f"{change_id} is '{change['status']}' and cannot be cancelled.")
    return {"status": "ok", "change": _record(change, "cancelled")}


def list_changes(limit: int = 20) -> dict:
    """History of proposed, applied, failed, cancelled and expired changes, newest first."""
    now = _iso(_now())
    rows = []
    for c in _all_changes().values():
        if c["status"] == "proposed" and _is_expired(c, now):
            c = {**c, "status": "expired"}
        rows.append(c)
    rows.sort(key=lambda c: c.get("proposed_at", ""), reverse=True)
    counts: dict[str, int] = {}
    for c in rows:
        counts[c["status"]] = counts.get(c["status"], 0) + 1
    return {"status": "ok", "total": len(rows), "counts": counts, "changes": rows[:limit]}
