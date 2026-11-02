from sre_mcp.cost.tools import billing


def test_summary_matches_prototype_numbers():
    s = billing.get_cost_summary()
    assert s["month"] == "2026-09"
    assert s["total_cost"] == 12450
    assert s["previous_total_cost"] == 11485
    assert s["change_pct"] == 8.4


def test_cost_by_service_sorted_and_adds_up():
    r = billing.get_cost_by_service()
    rows = r["by_service"]
    assert rows[0]["service"] == "Kubernetes Engine" and rows[0]["cost"] == 5200
    assert sum(x["cost"] for x in rows) == r["total_cost"]


def test_cost_by_project_adds_up():
    r = billing.get_cost_by_project()
    assert sum(x["cost"] for x in r["by_project"]) == 12450


def test_compare_months_top_driver_is_gke():
    r = billing.compare_months()
    assert r["by_service"][0]["service"] == "Kubernetes Engine"
    assert r["by_service"][0]["change_amount"] == 600
    assert r["total_change_amount"] == 965


def test_unknown_month_returns_error_not_crash():
    assert billing.get_cost_summary("1999-01")["status"] == "error"


def test_first_month_has_no_comparison():
    assert billing.compare_months("2026-08")["status"] == "error"


def test_compare_months_includes_totals():
    r = billing.compare_months()
    assert r["current_total_cost"] == 12450
    assert r["previous_total_cost"] == 11485
    assert r["total_change_pct"] == 8.4
