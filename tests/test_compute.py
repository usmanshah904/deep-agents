from sre_mcp.cost.tools import billing, compute_cost, savings


def _billed(service):
    return next(r["cost"] for r in billing.get_cost_by_service()["by_service"] if r["service"] == service)


def test_compute_adds_up_to_billing_compute_total():
    r = compute_cost.get_compute_cost_by_instance()
    assert r["total_compute_cost"] == _billed("Compute Engine") == 2400
    assert r["vm_cost"] + r["unused_resources_cost"] == r["total_compute_cost"]


def test_instances_sorted_limited_and_filtered():
    rows = compute_cost.get_compute_cost_by_instance(limit=2)["top_instances"]
    assert [r["cost"] for r in rows] == [450, 450]
    assert compute_cost.get_compute_cost_by_instance(project="staging")["total_compute_cost"] == 700
    assert compute_cost.get_compute_cost_by_instance(project="nope")["status"] == "error"


def test_waste_flags_idle_oversized_and_unused_but_not_healthy_vms():
    r = compute_cost.get_compute_waste()
    assert [v["name"] for v in r["idle_vms"]] == ["legacy-ftp"]
    oversized = {v["name"] for v in r["oversized_vms"]}
    assert {"web-vm-1", "staging-app"} <= oversized
    assert not oversized & {"legacy-ftp", "db-proxy", "ci-runner"}
    assert len(r["unused_resources"]) == 4
    for v in r["oversized_vms"]:
        assert 0 < v["estimated_monthly_saving"] < v["cost"]


def test_commitments_only_for_steady_uncovered_prod_vms():
    r = compute_cost.get_compute_commitment_coverage()
    assert {c["name"] for c in r["cud_candidates"]} == {"web-vm-1", "web-vm-2"}
    assert r["coverage_pct"] == 18.2  # db-proxy $200 of $1,100 steady prod spend
    assert {s["name"] for s in r["spot_candidates"]} == {"report-worker", "ci-runner"}
    for c in r["cud_candidates"]:
        assert c["cost_after_rightsizing"] < c["cost"]


def test_compute_savings_in_estimate_without_double_counting():
    r = savings.estimate_savings()
    ce = [o for o in r["opportunities"] if o["service"] == "Compute Engine"]
    assert len(ce) == 4
    assert 0 < sum(o["estimated_monthly_saving"] for o in ce) < _billed("Compute Engine")
    assert "Compute Engine" not in r["not_covered"]
