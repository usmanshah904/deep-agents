import json
from pathlib import Path

from .base import DataSource

_MOCK_DIR = Path(__file__).parent / "mock"


def _load(name: str) -> dict:
    with open(_MOCK_DIR / name, encoding="utf-8") as f:
        return json.load(f)


class MockDataSource(DataSource):
    def get_billing_records(self) -> list[dict]:
        return _load("billing.json")["records"]

    def get_gke_workloads(self) -> dict:
        return _load("gke.json")

    def get_bigquery_queries(self) -> dict:
        return _load("bigquery.json")

    def get_compute_resources(self) -> dict:
        return _load("compute.json")

    def get_storage_buckets(self) -> dict:
        return _load("storage.json")
