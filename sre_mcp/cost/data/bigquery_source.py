"""Costs from a Cloud Billing detailed (resource-level) export table in BigQuery. Read-only.

Settings (environment):
  BQ_BILLING_TABLE  project.dataset.table of the export, e.g.
                    my-project.billing_export.gcp_billing_export_resource_v1_012345_6789AB_CDEF01
  BQ_API_URL        BigQuery REST endpoint. Default: real BigQuery. For the floci emulator:
                    http://localhost:4588
  GCP_PROJECT       project that runs the query jobs (default demo-project)
  GCP_ACCESS_TOKEN  bearer token, only needed for real BigQuery (use a read-only account)

Every cost (billing totals, GKE workloads, VMs, unused disks and IPs, buckets) comes from the
export. What billing cannot know still comes from the mock files: GKE requests and usage, VM
CPU and memory use, bucket sizes and storage classes (later: Cloud Monitoring and the
inventory APIs), and BigQuery query details (later: INFORMATION_SCHEMA.JOBS).
"""

import copy
import os
import time

import httpx

from .mock_source import MockDataSource

DEFAULT_API_URL = "https://bigquery.googleapis.com"
CACHE_SECONDS = 60  # one answer often calls several tools that run the same query

# Net cost of one row: cost plus its credits (credits are negative).
NET = "cost + IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) AS c), 0)"


def label(key: str) -> str:
    """SQL for the value of one label (resource labels, e.g. team or k8s-namespace)."""
    return f"(SELECT l.value FROM UNNEST(labels) AS l WHERE l.key = '{key}')"


class BigQueryError(Exception):
    pass


class BigQueryDataSource(MockDataSource):
    _cache: dict[str, tuple[float, list]] = {}

    def __init__(self):
        self.table = os.getenv("BQ_BILLING_TABLE", "")
        if self.table.count(".") != 2 or any(ch in self.table for ch in "`'\" ;"):
            raise BigQueryError("Set BQ_BILLING_TABLE to project.dataset.table of the billing export.")
        self.url = os.getenv("BQ_API_URL", DEFAULT_API_URL).rstrip("/")
        self.project = os.getenv("GCP_PROJECT", "demo-project")
        token = os.getenv("GCP_ACCESS_TOKEN")
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}

    # ---------- running queries ----------

    def _call(self, method: str, path: str, **kwargs) -> dict:
        for attempt in range(2):
            try:
                resp = httpx.request(method, f"{self.url}/bigquery/v2/projects/{self.project}{path}",
                                     headers=self.headers, timeout=120, **kwargs)
            except httpx.HTTPError as exc:
                raise BigQueryError(f"Cannot reach BigQuery at {self.url}: {exc}") from exc
            # floci starts its SQL engine on the first query; that can take longer than its wait.
            if resp.status_code == 503 and attempt == 0:
                continue
            if resp.status_code >= 400:
                raise BigQueryError(f"BigQuery error {resp.status_code}: {resp.text[:300]}")
            return resp.json()
        raise BigQueryError("BigQuery is not available.")

    def query(self, sql: str) -> list[dict]:
        """Run a query; return rows as dicts of strings (BigQuery REST returns values as text)."""
        sql = sql.replace("{billing_table}", f"`{self.table}`")
        hit = self._cache.get(sql)
        if hit and time.time() - hit[0] < CACHE_SECONDS:
            return copy.deepcopy(hit[1])
        result = self._call("POST", "/queries", json={"query": sql, "useLegacySql": False, "timeoutMs": 60000})
        job = result.get("jobReference", {})
        rows: list[list] = []
        for _ in range(100):
            if result.get("jobComplete", True):
                names = [f["name"] for f in result.get("schema", {}).get("fields", [])]
                rows += [dict(zip(names, (cell.get("v") for cell in row["f"]))) for row in result.get("rows", [])]
                if not result.get("pageToken"):
                    self._cache[sql] = (time.time(), rows)
                    return copy.deepcopy(rows)
            else:
                time.sleep(1)
            params = {k: v for k, v in {"pageToken": result.get("pageToken"),
                                         "location": job.get("location")}.items() if v}
            result = self._call("GET", f"/queries/{job['jobId']}", params=params)
        raise BigQueryError("BigQuery query did not finish in time.")

    def latest_month(self) -> str:
        """Latest invoice month in the export, as YYYYMM."""
        rows = self.query("SELECT MAX(invoice.month) AS month FROM {billing_table}")
        if not rows or not rows[0]["month"]:
            raise BigQueryError("The billing export table is empty.")
        return rows[0]["month"]

    def _costs_by(self, service: str, key_sql: str, month: str) -> dict[str, float]:
        rows = self.query(f"SELECT {key_sql} AS k, ROUND(SUM({NET}), 2) AS cost FROM {{billing_table}} "
                          f"WHERE service.description = '{service}' AND invoice.month = '{month}' GROUP BY k")
        return {r["k"]: float(r["cost"]) for r in rows if r["k"] is not None}

    # ---------- the DataSource interface ----------

    def get_billing_records(self) -> list[dict]:
        rows = self.query(f"""
            SELECT invoice.month AS month, service.description AS service, project.id AS project,
                   ROUND(SUM({NET}), 2) AS cost
            FROM {{billing_table}}
            GROUP BY month, service, project""")
        return [{"month": f"{r['month'][:4]}-{r['month'][4:]}", "service": r["service"], "project": r["project"],
                 "cost": float(r["cost"])} for r in rows if r["month"] and r["cost"] is not None]

    def get_gke_workloads(self) -> dict:
        data = super().get_gke_workloads()
        month = self.latest_month()
        key = f"CONCAT({label('goog-k8s-cluster-name')}, '/', {label('k8s-namespace')}, '/', {label('k8s-workload-name')})"
        costs = self._costs_by("Kubernetes Engine", key, month)
        for w in data["workloads"]:
            w["cost"] = costs.get(f"{w['cluster']}/{w['namespace']}/{w['workload']}", 0.0)
        return {**data, "month": f"{month[:4]}-{month[4:]}"}

    def get_compute_resources(self) -> dict:
        data = super().get_compute_resources()
        month = self.latest_month()
        costs = self._costs_by("Compute Engine", "resource.name", month)
        for item in data["instances"] + data["unused_resources"]:
            item["cost"] = costs.get(item["name"], 0.0)
        return {**data, "month": f"{month[:4]}-{month[4:]}"}

    def get_storage_buckets(self) -> dict:
        data = super().get_storage_buckets()
        month = self.latest_month()
        rows = self.query(f"SELECT resource.name AS bucket, sku.description AS sku, ROUND(SUM({NET}), 2) AS cost "
                          f"FROM {{billing_table}} WHERE service.description = 'Cloud Storage' "
                          f"AND invoice.month = '{month}' GROUP BY bucket, sku")
        for b in data["buckets"]:
            parts = {"storage_cost": 0.0, "operations_cost": 0.0, "egress_cost": 0.0}
            for r in (r for r in rows if r["bucket"] == b["name"]):
                sku = r["sku"].lower()
                kind = "operations_cost" if "operations" in sku else \
                    "egress_cost" if ("download" in sku or "egress" in sku or "network" in sku) else "storage_cost"
                parts[kind] += float(r["cost"])
            b.update({k: round(v, 2) for k, v in parts.items()}, cost=round(sum(parts.values()), 2))
        return {**data, "month": f"{month[:4]}-{month[4:]}"}
