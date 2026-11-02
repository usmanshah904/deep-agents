from sre_mcp.cost.tools import billing, savings, storage_cost


def _billed(service):
    return next(r["cost"] for r in billing.get_cost_by_service()["by_service"] if r["service"] == service)


def test_storage_adds_up_to_billing_storage_total():
    r = storage_cost.get_storage_cost_by_bucket()
    assert r["total_storage_cost"] == _billed("Cloud Storage") == 1050
    assert r["storage_cost"] + r["operations_cost"] + r["egress_cost"] == r["total_storage_cost"]


def test_buckets_sorted_limited_and_filtered():
    rows = storage_cost.get_storage_cost_by_bucket(limit=2)["by_bucket"]
    assert [b["name"] for b in rows] == ["prod-app-assets", "analytics-raw-data"]
    assert storage_cost.get_storage_cost_by_bucket(project="analytics")["total_storage_cost"] == 400
    assert storage_cost.get_storage_cost_by_bucket(project="nope")["status"] == "error"


def test_class_changes_match_how_long_data_is_unread():
    r = storage_cost.get_storage_waste()
    targets = {c["bucket"]: c["target_class"] for c in r["class_changes"]}
    assert targets == {"prod-logs-archive": "ARCHIVE", "prod-db-backups": "COLDLINE", "analytics-raw-data": "NEARLINE"}
    assert "prod-app-assets" not in targets  # cold data read 20 days ago stays in Standard


def test_cleanups_lifecycle_and_egress_flags():
    r = storage_cost.get_storage_waste()
    assert {c["bucket"] for c in r["cleanups"]} == {"analytics-raw-data", "analytics-tmp"}
    assert "prod-app-assets" not in r["buckets_without_lifecycle_rules"]
    assert [e["bucket"] for e in r["high_egress"]] == ["prod-app-assets"]
    for row in r["class_changes"] + r["cleanups"]:
        assert row["estimated_monthly_saving"] > 0


def test_storage_savings_in_estimate_and_below_service_cost():
    r = savings.estimate_savings()
    gcs = [o for o in r["opportunities"] if o["service"] == "Cloud Storage"]
    assert len(gcs) == 2
    total = sum(o["estimated_monthly_saving"] for o in gcs)
    assert total == storage_cost.get_storage_waste()["total_estimated_monthly_saving"]
    assert 0 < total < _billed("Cloud Storage")
    assert "Cloud Storage" not in r["not_covered"]
