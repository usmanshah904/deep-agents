"""Checks for the eval runner itself: no Gemini, no network."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "evals"))

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage  # noqa: E402

import run_evals  # noqa: E402

KNOWN_TOOLS = {"get_cost_summary", "get_cost_by_service", "get_cost_by_project", "compare_months",
               "get_gke_cost_by_cluster", "get_gke_cost_by_namespace", "get_gke_top_workloads",
               "get_gke_overprovisioned_workloads", "get_bigquery_expensive_queries",
               "get_compute_cost_by_instance", "get_compute_waste", "get_compute_commitment_coverage",
               "get_storage_cost_by_bucket", "get_storage_waste", "estimate_savings",
               "list_metrics", "get_metric_timeseries", "get_resource_utilization", "search_logs",
               "get_recent_errors", "get_log_summary", "get_inventory", "propose_change",
               "apply_change", "cancel_change", "list_changes", "get_daily_costs", "get_daily_spikes",
               "get_top_resources", "get_unlabeled_spend", "run_billing_query", "check_incident_status"}


def _chat(answer: str, tool_output: str, calls=("get_cost_summary",)):
    return [
        HumanMessage("What was the bill?"),
        AIMessage("", tool_calls=[{"name": n, "args": {}, "id": f"c{i}"} for i, n in enumerate(calls)]
                  + [{"name": "read_file", "args": {"file_path": "/skills/billing-financial-metrics/SKILL.md"}, "id": "r"}]),
        *[ToolMessage(tool_output, tool_call_id=f"c{i}", name=n) for i, n in enumerate(calls)],
        AIMessage(answer),
    ]


def test_cases_file_is_valid():
    cases = run_evals.load_cases()
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids)), "case IDs must be unique"
    assert [c["priority"] for c in cases] == sorted(c["priority"] for c in cases)
    skills = {p.name for p in run_evals.agent.SKILLS_DIR.iterdir() if p.is_dir()}
    for c in cases:
        assert c["turns"] and isinstance(c["floci"], bool), c["id"]
        exp = c.get("expect", {})
        for name in [n for need in exp.get("tools", []) + exp.get("no_tools", []) for n in need.split("|")]:
            assert name in KNOWN_TOOLS, f"{c['id']}: unknown tool {name}"
        for name in [n for need in exp.get("skills", []) for n in need.split("|")]:
            assert name in skills, f"{c['id']}: unknown skill {name}"


def test_correct_answer_passes():
    case = {"expect": {"tools": ["get_cost_summary"], "skills": ["billing-financial-metrics"],
                       "contains": ["12450", "8.4"]}}
    t = run_evals.trace(_chat("Total was $12,450 (up 8.4%, about $12.5K).", '{"total_cost": 12450.0, "change_pct": 8.4}'))
    assert run_evals.score(case, t) == []


def test_made_up_number_fails():
    # The model added numbers itself: $1,659.80 is in no tool result.
    t = run_evals.trace(_chat("Together that is $1,659.80.", '{"a": 1015.2, "b": 644.5}'))
    assert run_evals.unsupported_numbers(t) == ["$1,659.80"]


def test_missing_tool_skill_and_text_fail():
    case = {"expect": {"tools": ["compare_months"], "skills": ["gke-cost-analysis"], "contains": ["GKE"],
                       "no_tools": ["get_cost_summary"]}}
    fails = run_evals.score(case, run_evals.trace(_chat("No idea.", "{}")))
    assert fails == ["did not call compare_months", "did not read skill gke-cost-analysis",
                     "answer missing 'GKE'", "called get_cost_summary"]


def test_apply_checks():
    ok = '{"status": "ok", "message": "chg-abc123 applied"}'
    msgs = _chat("Applied chg-abc123.", ok, calls=("apply_change",))
    t = run_evals.trace(msgs)
    assert t["applied"] and "apply_change" in t["tool_calls"]
    assert run_evals.score({"expect": {"apply_attempted": False, "applied": False}}, t) == [
        "tried apply_change", "change was applied"]
