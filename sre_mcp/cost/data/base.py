"""Data source interface. Tools call this; they never know where data comes from."""

from abc import ABC, abstractmethod


class DataSource(ABC):
    @abstractmethod
    def get_billing_records(self) -> list[dict]:
        """Monthly cost rows: {"month": "YYYY-MM", "service": str, "project": str, "cost": float}."""

    @abstractmethod
    def get_gke_workloads(self) -> dict:
        """{"month": str, "workloads": [{cluster, cluster_mode, namespace, workload, cost, batch,
        cpu_requested, cpu_used, mem_requested_gb, mem_used_gb}]}"""

    @abstractmethod
    def get_bigquery_queries(self) -> dict:
        """{"month": str, "pricing_model": str, "price_per_tb": float, "queries": [{query_id, project,
        user, table, tb_billed, cost, issue, fix, est_saving_pct}]}"""

    @abstractmethod
    def get_compute_resources(self) -> dict:
        """{"month": str, "instances": [{name, project, env, zone, machine_type, cost, cpu_util_pct,
        mem_util_pct, uptime_pct, batch, cud_covered}], "unused_resources": [{type, name, project,
        detail, age_days, cost}]}"""

    @abstractmethod
    def get_storage_buckets(self) -> dict:
        """{"month": str, "prices_per_gb": {storage_class: float}, "buckets": [{name, project, purpose,
        storage_class, location, current_gb, noncurrent_gb, storage_cost, operations_cost, egress_cost,
        cost, cold_data_pct, cold_data_last_read_days, deletable_gb, versioning, lifecycle_rules}]}"""
