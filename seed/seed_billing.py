"""Fills floci-gcp BigQuery with a Cloud Billing **detailed** (resource-level) export table.

Daily rows for Aug and Sep 2026 with the real export columns: service, SKU, project, labels,
location, resource name, usage, credits, invoice month. Costs come from the sample data in
sre_mcp/cost/data/mock, so every tool gives the same numbers on the mock files and on this table:
net cost (cost + credits) per month, service and project matches billing.json, and per
resource it matches gke.json, compute.json and storage.json (September).

Planted for the billing tools:
- Kubernetes Engine +$600 from Aug to Sep: payments-api (+$450) and web-staging (+$150).
- BigQuery +$350, with a spike day on 2026-09-17 in the analytics project.
- Unlabeled spend (no "team" label): legacy-ftp, old VM snapshots and unused static IPs.
GKE costs use the GKE cost allocation labels (goog-k8s-cluster-name, k8s-namespace,
k8s-workload-name). For simplicity all GKE cost is billed under "Kubernetes Engine".

Only runs against a local emulator (localhost). Run: python -m seed.seed_billing
Needs floci's BigQuery SQL engine for queries (Docker socket, see docker-compose.yml).
"""

import json
import os
import sys
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sre_mcp.observability import client

MOCK_DIR = Path(__file__).resolve().parent.parent / "sre_mcp" / "cost" / "data" / "mock"
BILLING_ACCOUNT = "012345-6789AB-CDEF01"
DATASET = "billing_export"
TABLE = "gcp_billing_export_resource_v1_" + BILLING_ACCOUNT.replace("-", "_")
SPIKE_DAY = "2026-09-17"  # BigQuery analytics spends ~6x a normal day
BATCH = 500

SERVICE_IDS = {"Kubernetes Engine": "CCD8-9BF1-090E", "Compute Engine": "6F81-5844-456A",
               "Cloud Storage": "95FF-2EF5-5EA1", "BigQuery": "24E6-581D-38E5",
               "Cloud SQL": "9662-B51E-5089", "Cloud Logging": "5490-F7B7-8DF6"}
PROJECT_NUMBERS = {"prod": "100000000001", "staging": "100000000002", "analytics": "100000000003"}
VM_SKUS = [("N2 Instance Core running in Americas", "hour", 0.7), ("N2 Instance Ram running in Americas", "gibibyte hour", 0.3)]
NAMESPACE_TEAMS = {"checkout": "payments", "search": "search", "web": "web", "data": "data",
                   "kube-system": "platform", "staging": "web", "ci": "platform"}
UNUSED_SKUS = {"disk": ("SSD backed PD Capacity", "gibibyte month"), "snapshot": ("Storage PD Snapshot", "gibibyte month"),
               "static_ip": ("Static Ip Charge", "hour")}
UNLABELED = {"legacy-ftp", "web-vm-snapshots-2025", "unused-external-ips"}
# August cost where it differs from September (the rest is the same both months).
AUGUST = {"payments-api": 650, "web-staging": 250, ("BigQuery", "analytics"): 2400, ("BigQuery", "prod"): 350,
          ("Cloud SQL", "prod"): 485}

_LABEL = {"name": "labels", "type": "RECORD", "mode": "REPEATED",
          "fields": [{"name": "key", "type": "STRING"}, {"name": "value", "type": "STRING"}]}
SCHEMA = {"fields": [
    {"name": "billing_account_id", "type": "STRING"},
    {"name": "service", "type": "RECORD", "fields": [
        {"name": "id", "type": "STRING"}, {"name": "description", "type": "STRING"}]},
    {"name": "sku", "type": "RECORD", "fields": [
        {"name": "id", "type": "STRING"}, {"name": "description", "type": "STRING"}]},
    {"name": "usage_start_time", "type": "TIMESTAMP"},
    {"name": "usage_end_time", "type": "TIMESTAMP"},
    {"name": "project", "type": "RECORD", "fields": [
        {"name": "id", "type": "STRING"}, {"name": "number", "type": "STRING"},
        {"name": "name", "type": "STRING"}, _LABEL]},
    _LABEL,
    {"name": "system_labels", "type": "RECORD", "mode": "REPEATED",
     "fields": [{"name": "key", "type": "STRING"}, {"name": "value", "type": "STRING"}]},
    {"name": "location", "type": "RECORD", "fields": [
        {"name": "location", "type": "STRING"}, {"name": "country", "type": "STRING"},
        {"name": "region", "type": "STRING"}, {"name": "zone", "type": "STRING"}]},
    {"name": "resource", "type": "RECORD", "fields": [
        {"name": "name", "type": "STRING"}, {"name": "global_name", "type": "STRING"}]},
    {"name": "export_time", "type": "TIMESTAMP"},
    {"name": "cost", "type": "FLOAT"},
    {"name": "currency", "type": "STRING"},
    {"name": "currency_conversion_rate", "type": "FLOAT"},
    {"name": "usage", "type": "RECORD", "fields": [
        {"name": "amount", "type": "FLOAT"}, {"name": "unit", "type": "STRING"}]},
    {"name": "credits", "type": "RECORD", "mode": "REPEATED", "fields": [
        {"name": "name", "type": "STRING"}, {"name": "amount", "type": "FLOAT"},
        {"name": "type", "type": "STRING"}]},
    {"name": "invoice", "type": "RECORD", "fields": [{"name": "month", "type": "STRING"}]},
    {"name": "cost_type", "type": "STRING"},
]}


def _load(name: str) -> dict:
    return json.loads((MOCK_DIR / name).read_text(encoding="utf-8"))


def line_items() -> list[dict]:
    """One item per resource (or service and project): its monthly net cost per month and its SKUs."""
    items = []

    def add(service, project, cost, skus, resource=None, labels=None, zone=None, credit=None):
        aug = AUGUST.get(resource, AUGUST.get((service, project), cost))
        items.append({"service": service, "project": project, "resource": resource, "labels": labels or {},
                      "zone": zone, "skus": skus, "credit": credit, "costs": {"2026-08": aug, "2026-09": cost}})

    for w in _load("gke.json")["workloads"]:
        project = "prod" if w["cluster"].startswith("prod") else "staging"
        labels = {"goog-k8s-cluster-name": w["cluster"], "k8s-namespace": w["namespace"],
                  "k8s-workload-name": w["workload"], "team": NAMESPACE_TEAMS[w["namespace"]]}
        add("Kubernetes Engine", project, w["cost"], VM_SKUS, w["workload"], labels, "us-central1-a",
            "SUSTAINED_USAGE_DISCOUNT")
    compute = _load("compute.json")
    for vm in compute["instances"]:
        labels = {} if vm["name"] in UNLABELED else {"team": "web" if vm["project"] == "prod" else "platform"}
        add("Compute Engine", vm["project"], vm["cost"], VM_SKUS, vm["name"], labels, vm["zone"],
            "COMMITTED_USAGE_DISCOUNT" if vm["cud_covered"] else "SUSTAINED_USAGE_DISCOUNT")
    for u in compute["unused_resources"]:
        labels = {} if u["name"] in UNLABELED else {"team": "data" if u["project"] == "prod" else "web"}
        add("Compute Engine", u["project"], u["cost"], [(*UNUSED_SKUS[u["type"]], 1.0)], u["name"], labels, "us-central1-a")
    for b in _load("storage.json")["buckets"]:
        parts = [("Standard Storage US Multi-region", "gibibyte month", b["storage_cost"]),
                 ("Class A Operations", "count", b["operations_cost"]),
                 ("Download Worldwide Destinations (excluding Asia & Australia)", "gibibyte", b["egress_cost"])]
        add("Cloud Storage", b["project"], b["cost"], [p for p in parts if p[2]], b["name"],
            {"team": "data" if b["project"] == "analytics" else "web"})
    for project, cost in (("analytics", 2700), ("prod", 400)):
        add("BigQuery", project, cost, [("Analysis (us)", "tebibyte", 0.85), ("Active Logical Storage (us)", "gibibyte month", 0.15)],
            labels={"team": "data"})
    add("Cloud SQL", "prod", 500, [("Cloud SQL for PostgreSQL: Zonal - vCPU in Americas", "hour", 0.6),
                                   ("Cloud SQL for PostgreSQL: Zonal - RAM in Americas", "gibibyte hour", 0.4)],
        "payments-db", {"team": "payments"}, "us-central1-a")
    add("Cloud Logging", "staging", 200, [("Log Storage cost", "gibibyte", 1.0)], labels={"team": "platform"})
    return items


def _days(month: str) -> list[datetime]:
    start = datetime.strptime(month, "%Y-%m").replace(tzinfo=timezone.utc)
    end = (start + timedelta(days=32)).replace(day=1)
    return [start + timedelta(days=d) for d in range((end - start).days)]


def _split_cents(total_cents: int, weights: list[float]) -> list[int]:
    """Split whole cents by weight so the parts add up exactly."""
    raw = [total_cents * w / sum(weights) for w in weights]
    parts = [int(r) for r in raw]
    for i in sorted(range(len(raw)), key=lambda i: raw[i] - parts[i], reverse=True)[: total_cents - sum(parts)]:
        parts[i] += 1
    return parts


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def build_rows() -> list[dict]:
    rows = []
    for item in line_items():
        service, project = item["service"], item["project"]
        service_id = SERVICE_IDS[service]
        for month, net in item["costs"].items():
            days = _days(month)
            spike = service == "BigQuery" and project == "analytics"
            weights = [6.0 if spike and d.strftime("%Y-%m-%d") == SPIKE_DAY else 1.0 for d in days]
            sku_cents = _split_cents(round(net * 100), [s[2] for s in item["skus"]])
            for n, (sku, unit, _) in enumerate(item["skus"]):
                for day, cents in zip(days, _split_cents(sku_cents[n], weights)):
                    credit = round(cents / 9) if item["credit"] else 0  # discount = ~10% of the gross cost
                    rows.append({
                        "billing_account_id": BILLING_ACCOUNT,
                        "service": {"id": service_id, "description": service},
                        "sku": {"id": f"{service_id[:4]}-{n + 1:04d}-{zlib.crc32(sku.encode()) % 10000:04d}", "description": sku},
                        "usage_start_time": _iso(day),
                        "usage_end_time": _iso(day + timedelta(days=1)),
                        "project": {"id": project, "number": PROJECT_NUMBERS[project], "name": project,
                                    "labels": [{"key": "env", "value": "staging" if project == "staging" else "prod"}]},
                        "labels": [{"key": k, "value": v} for k, v in item["labels"].items()],
                        "system_labels": [],
                        "location": {"location": "us-central1", "country": "US", "region": "us-central1",
                                     "zone": item["zone"]},
                        "resource": {"name": item["resource"],
                                     "global_name": f"//{service.lower().replace(' ', '')}.googleapis.com/projects/{project}/{item['resource']}"
                                     if item["resource"] else None},
                        "export_time": _iso(day + timedelta(days=1, hours=5)),
                        "cost": (cents + credit) / 100,
                        "currency": "USD",
                        "currency_conversion_rate": 1.0,
                        "usage": {"amount": 1.0, "unit": unit},
                        "credits": [{"name": item["credit"].replace("_", " ").title(), "amount": -credit / 100,
                                     "type": item["credit"]}] if credit else [],
                        "invoice": {"month": month.replace("-", "")},
                        "cost_type": "regular",
                    })
    return rows


def table_id() -> str:
    return f"{client.project()}.{DATASET}.{TABLE}"


def main() -> None:
    url = os.getenv("OBS_API_URL", client.DEFAULT_URL)
    if not any(h in url for h in ("localhost", "127.0.0.1")):
        sys.exit(f"Refusing to seed {url}: only a local emulator is allowed.")
    base = f"/bigquery/v2/projects/{client.project()}"
    try:
        client.post(f"{base}/datasets", {"datasetReference": {"datasetId": DATASET}})
    except client.ApiError as exc:
        if exc.status != 409:  # 409 = already exists
            raise
    try:
        client._request("DELETE", f"{base}/datasets/{DATASET}/tables/{TABLE}")
    except client.ApiError as exc:
        if exc.status != 404:
            raise
    client.post(f"{base}/datasets/{DATASET}/tables", {"tableReference": {"tableId": TABLE}, "schema": SCHEMA})
    rows = build_rows()
    for i in range(0, len(rows), BATCH):
        result = client.post(f"{base}/datasets/{DATASET}/tables/{TABLE}/insertAll",
                             {"rows": [{"json": r} for r in rows[i:i + BATCH]]}, timeout=180)
        if result.get("insertErrors"):
            sys.exit(f"Insert failed: {str(result['insertErrors'])[:300]}")
    print(f"Created {table_id()} with {len(rows)} daily rows (Aug and Sep 2026).")


if __name__ == "__main__":
    main()
