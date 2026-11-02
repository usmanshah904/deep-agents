from sre_mcp.cost.tools import billing, bigquery_cost, gke_cost, savings


def test_gke_workloads_add_up_to_billing_gke_total():
    gke_billed = next(r["cost"] for r in billing.get_cost_by_service()["by_service"] if r["service"] == "Kubernetes Engine")
    assert gke_cost.get_gke_cost_by_cluster()["total_gke_cost"] == gke_billed


def test_cluster_and_namespace_breakdowns():
    clusters = gke_cost.get_gke_cost_by_cluster()["by_cluster"]
    assert clusters[0]["cluster"] == "prod-cluster" and clusters[0]["cost"] == 4300
    ns = gke_cost.get_gke_cost_by_namespace("staging-cluster")
    assert ns["total_cost"] == 900
    assert gke_cost.get_gke_cost_by_namespace("nope")["status"] == "error"


def test_top_workloads_sorted_and_limited():
    rows = gke_cost.get_gke_top_workloads(limit=2)["top_workloads"]
    assert [r["workload"] for r in rows] == ["payments-api", "search-indexer"]


def test_overprovisioned_flags_waste_but_not_healthy_workloads():
    r = gke_cost.get_gke_overprovisioned_workloads()
    names = {x["workload"] for x in r["overprovisioned"]}
    assert "payments-api" in names and "web-staging" in names
    assert "system-components" not in names and "frontend" not in names
    for x in r["overprovisioned"]:
        assert 0 < x["estimated_monthly_saving"] < x["cost"]


def test_bigquery_queries_sorted_with_savings():
    r = bigquery_cost.get_bigquery_expensive_queries(limit=3)
    costs = [q["cost"] for q in r["expensive_queries"]]
    assert costs == sorted(costs, reverse=True) and len(costs) == 3
    assert all(q["estimated_monthly_saving"] < q["cost"] for q in r["expensive_queries"])


def test_estimate_savings_is_ranked_and_realistic():
    r = savings.estimate_savings()
    vals = [o["estimated_monthly_saving"] for o in r["opportunities"]]
    assert vals == sorted(vals, reverse=True)
    assert 0 < r["total_estimated_monthly_saving"] < billing.get_cost_summary()["total_cost"]


def test_no_double_counting_on_gke():
    r = savings.estimate_savings()
    gke_total = sum(o["estimated_monthly_saving"] for o in r["opportunities"] if o["service"] == "GKE")
    assert gke_total < gke_cost.get_gke_cost_by_cluster()["total_gke_cost"]
