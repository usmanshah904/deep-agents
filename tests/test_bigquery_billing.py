"""BigQuery billing source and the SQL billing tools.

Offline tests fake the query results from the seed rows. The live test runs the real SQL on
floci's BigQuery and is skipped when floci or the billing table is not there.
"""

import json
import urllib.request
from collections import defaultdict

import httpx
import pytest

from seed import seed_billing
from sre_mcp.cost.data import get_data_source
from sre_mcp.cost.data.bigquery_source import BigQueryDataSource, BigQueryError
from sre_mcp.cost.tools import billing, billing_sql, compute_cost, gke_cost, savings, storage_cost

TABLE = "demo-project.billing_export.gcp_billing_export_resource_v1_012345_6789AB_CDEF01"


def _net(row) -> float:
    return row["cost"] + sum(c["amount"] for c in row["credits"])


def _label(row, key):
    return next((l["value"] for l in row["labels"] if l["key"] == key), None)


def _group(rows, key, **extra):
    totals = defaultdict(float)
    for r in rows:
        totals[key(r)] += _net(r)
    return totals


def fake_query(sql: str) -> list[dict]:
    """Answers the source's queries from the seed rows (stands in for BigQuery)."""
    rows = seed_billing.build_rows()
    month = next((m for m in ("202608", "202609") if f"'{m}'" in sql), None)
    if month:
        rows = [r for r in rows if r["invoice"]["month"] == month]
    for service in ("Kubernetes Engine", "Compute Engine", "Cloud Storage", "BigQuery"):
        if f"service.description = '{service}'" in sql:
            rows = [r for r in rows if r["service"]["description"] == service]
    if "MAX(invoice.month)" in sql:
        return [{"month": "202609"}]
    if "GROUP BY month, service, project" in sql:
        t = _group(rows, lambda r: (r["invoice"]["month"], r["service"]["description"], r["project"]["id"]))
        return [{"month": m, "service": s, "project": p, "cost": str(round(c, 2))} for (m, s, p), c in t.items()]
    if "CONCAT(" in sql:
        t = _group(rows, lambda r: "/".join(_label(r, k) for k in ("goog-k8s-cluster-name", "k8s-namespace", "k8s-workload-name")))
        return [{"k": k, "cost": str(round(c, 2))} for k, c in t.items()]
    if "resource.name AS k" in sql:
        t = _group(rows, lambda r: r["resource"]["name"])
        return [{"k": k, "cost": str(round(c, 2))} for k, c in t.items()]
    if "sku.description AS sku" in sql:
        t = _group(rows, lambda r: (r["resource"]["name"], r["sku"]["description"]))
        return [{"bucket": b, "sku": s, "cost": str(round(c, 2))} for (b, s), c in t.items()]
    if "DATE(usage_start_time)" in sql:
        with_project = "project.id AS project" in sql
        t = _group(rows, lambda r: (r["usage_start_time"][:10], r["service"]["description"],
                                    r["project"]["id"] if with_project else None))
        return [{"day": d, "service": s, **({"project": p} if with_project else {}), "cost": str(round(c, 2))}
                for (d, s, p), c in t.items()]
    if "NOT EXISTS" in sql:
        rows = [r for r in rows if _label(r, "team") is None]
        t = _group(rows, lambda r: (r["service"]["description"], r["project"]["id"], r["resource"]["name"]))
        return [{"service": s, "project": p, "resource": n, "cost": str(round(c, 2))} for (s, p, n), c in t.items()]
    if "resource.name IS NOT NULL" in sql:
        t = _group([r for r in rows if r["resource"]["name"]],
                   lambda r: (r["service"]["description"], r["project"]["id"], r["resource"]["name"]))
        top = sorted(t.items(), key=lambda kv: -kv[1])[:10]
        return [{"service": s, "project": p, "resource": n, "cost": str(round(c, 2))} for (s, p, n), c in top]
    if sql.startswith("SELECT ROUND(SUM("):
        return [{"cost": str(round(sum(_net(r) for r in rows), 2))}]
    raise AssertionError(f"unexpected query: {sql[:120]}")


@pytest.fixture
def bq(monkeypatch):
    monkeypatch.setenv("COST_DATA_SOURCE", "bigquery")
    monkeypatch.setenv("BQ_BILLING_TABLE", TABLE)
    monkeypatch.setattr(BigQueryDataSource, "query", lambda self, sql: fake_query(" ".join(sql.split())))


def _without_costs(value):
    """Same structure, numbers rounded, to compare mock and BigQuery results."""
    return json.loads(json.dumps(value), parse_float=lambda f: round(float(f), 2))


# ---------- the seed table ----------

def test_seed_matches_the_mock_files():
    rows = seed_billing.build_rows()
    by_month = _group(rows, lambda r: r["invoice"]["month"])
    assert {m: round(c, 2) for m, c in by_month.items()} == {"202608": 11485, "202609": 12450}
    mock = json.loads((seed_billing.MOCK_DIR / "billing.json").read_text())["records"]
    projects = defaultdict(float)
    for r in mock:
        projects[(r["month"].replace("-", ""), r["project"])] += r["cost"]
    seeded = _group(rows, lambda r: (r["invoice"]["month"], r["project"]["id"]))
    assert {k: round(v, 2) for k, v in seeded.items()} == dict(projects)


def test_seed_has_the_planted_problems():
    rows = [r for r in seed_billing.build_rows() if r["invoice"]["month"] == "202609"]
    unlabeled = _group([r for r in rows if _label(r, "team") is None], lambda r: r["resource"]["name"])
    assert {k: round(v, 2) for k, v in unlabeled.items()} == {"legacy-ftp": 120, "web-vm-snapshots-2025": 50,
                                                              "unused-external-ips": 30}
    bq_days = _group([r for r in rows if r["service"]["description"] == "BigQuery" and r["project"]["id"] == "analytics"],
                     lambda r: r["usage_start_time"][:10])
    assert max(bq_days, key=bq_days.get) == seed_billing.SPIKE_DAY
    assert {f["name"] for f in seed_billing.SCHEMA["fields"]} >= set(rows[0])
    assert seed_billing.TABLE == "gcp_billing_export_resource_v1_012345_6789AB_CDEF01"


# ---------- every cost tool gives the same numbers on BigQuery as on the mock files ----------

COST_TOOLS = [billing.get_cost_summary, billing.get_cost_by_project, billing.compare_months,
              gke_cost.get_gke_cost_by_cluster, gke_cost.get_gke_cost_by_namespace, gke_cost.get_gke_top_workloads,
              gke_cost.get_gke_overprovisioned_workloads, compute_cost.get_compute_cost_by_instance,
              compute_cost.get_compute_waste, compute_cost.get_compute_commitment_coverage,
              storage_cost.get_storage_cost_by_bucket, storage_cost.get_storage_waste]


@pytest.mark.parametrize("tool", COST_TOOLS, ids=lambda t: t.__name__)
def test_cost_tools_match_mock(tool, monkeypatch, bq):
    from_bigquery = _without_costs(tool())
    monkeypatch.setenv("COST_DATA_SOURCE", "mock")
    assert from_bigquery == _without_costs(tool())


def test_savings_total_matches_mock(monkeypatch, bq):
    total = savings.estimate_savings()["total_estimated_monthly_saving"]
    monkeypatch.setenv("COST_DATA_SOURCE", "mock")
    assert total == savings.estimate_savings()["total_estimated_monthly_saving"]


def test_services_use_export_names(bq):
    services = {r["service"] for r in billing.get_cost_by_service()["by_service"]}
    assert {"Kubernetes Engine", "Cloud SQL", "Cloud Logging"} <= services


# ---------- the SQL tools ----------

def test_daily_costs_add_up_to_the_month(bq):
    r = billing_sql.get_daily_costs()
    assert r["month"] == "2026-09" and len(r["days"]) == 30 and r["month_total"] == 12450


def test_spike_day_found(bq):
    spikes = billing_sql.get_daily_spikes()["spikes"]
    assert spikes[0]["day"] == "2026-09-17" and spikes[0]["service"] == "BigQuery"
    assert spikes[0]["project"] == "analytics" and spikes[0]["increase_pct"] > 400


def test_unlabeled_spend(bq):
    r = billing_sql.get_unlabeled_spend()
    assert r["unlabeled_cost"] == 200 and r["total_cost"] == 12450 and r["unlabeled_pct"] == 1.6
    assert [i["resource"] for i in r["items"]] == ["legacy-ftp", "web-vm-snapshots-2025", "unused-external-ips"]


def test_top_resources(bq):
    top = billing_sql.get_top_resources()["resources"]
    assert top[0] == {"service": "Kubernetes Engine", "project": "prod", "resource": "payments-api", "cost": 1100.0}


def test_sql_tools_need_bigquery():
    r = billing_sql.get_daily_costs()
    assert r["status"] == "error" and "COST_DATA_SOURCE=bigquery" in r["message"]


@pytest.mark.parametrize("sql", [
    "DELETE FROM {billing_table} WHERE true",
    "SELECT 1; DROP TABLE x",
    "SELECT * FROM {billing_table} -- comment",
    "UPDATE t SET cost = 0",
    "WITH a AS (SELECT 1) INSERT INTO t SELECT * FROM a",
])
def test_run_billing_query_refuses_writes(sql, bq):
    assert billing_sql.run_billing_query(sql)["status"] == "error"


def test_run_billing_query_rejects_bad_input(bq):
    assert billing_sql.get_daily_costs(service="x'; DROP")["status"] == "error"
    assert billing_sql.get_unlabeled_spend(label_key="team' OR '1'='1")["status"] == "error"
    assert billing_sql.get_daily_costs(month="Sept")["status"] == "error"


# ---------- REST details ----------

def test_rest_paging_and_schema(monkeypatch):
    monkeypatch.setenv("BQ_BILLING_TABLE", TABLE)
    monkeypatch.setenv("BQ_API_URL", "http://localhost:4588")
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        schema = {"fields": [{"name": "month"}, {"name": "cost"}]}
        if method == "POST":
            body = {"jobComplete": True, "jobReference": {"jobId": "j1", "location": "US"}, "pageToken": "p2",
                    "schema": schema, "rows": [{"f": [{"v": "202609"}, {"v": "1.5"}]}]}
        else:
            body = {"jobComplete": True, "schema": schema, "rows": [{"f": [{"v": "202608"}, {"v": "2.5"}]}]}
        return httpx.Response(200, json=body)

    monkeypatch.setattr(httpx, "request", fake_request)
    BigQueryDataSource._cache.clear()
    rows = BigQueryDataSource().query("SELECT month, cost FROM {billing_table} -- paging test")
    assert rows == [{"month": "202609", "cost": "1.5"}, {"month": "202608", "cost": "2.5"}]
    assert f"`{TABLE}`" in calls[0][2]["json"]["query"]
    assert calls[1][2]["params"] == {"pageToken": "p2", "location": "US"}


def test_table_name_is_checked(monkeypatch):
    monkeypatch.setenv("BQ_BILLING_TABLE", "x.y.z`; DROP TABLE t")
    with pytest.raises(BigQueryError):
        BigQueryDataSource()


# ---------- live: real SQL on floci ----------

def _floci_table() -> bool:
    try:
        urllib.request.urlopen("http://localhost:4588/bigquery/v2/projects/demo-project/datasets/"
                               f"{seed_billing.DATASET}/tables/{seed_billing.TABLE}", timeout=3)
    except OSError:
        return False
    return True


@pytest.mark.skipif(not _floci_table(), reason="floci or the billing table is not there (python -m seed.seed_billing)")
def test_live_sql_on_floci_matches_mock(monkeypatch):
    monkeypatch.setenv("COST_DATA_SOURCE", "bigquery")
    monkeypatch.setenv("BQ_BILLING_TABLE", TABLE)
    monkeypatch.setenv("BQ_API_URL", "http://localhost:4588")
    assert isinstance(get_data_source(), BigQueryDataSource)
    live = {t.__name__: _without_costs(t()) for t in COST_TOOLS}
    spikes = billing_sql.get_daily_spikes()
    unlabeled = billing_sql.get_unlabeled_spend()
    monkeypatch.setenv("COST_DATA_SOURCE", "mock")
    for name, tool in ((t.__name__, t) for t in COST_TOOLS):
        assert live[name] == _without_costs(tool()), name
    assert spikes["spikes"][0]["day"] == "2026-09-17"
    assert unlabeled["unlabeled_cost"] == 200
