"""Setup checks that need no Gemini key and no network (MCP server runs locally)."""

import asyncio
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel  # noqa: E402
from langchain_core.messages import AIMessage  # noqa: E402

import agent  # noqa: E402
from deepagents.middleware.skills import _list_skills_with_errors  # noqa: E402

HERE = Path(__file__).resolve().parent.parent
EXPECTED_SKILLS = {
    "billing-financial-metrics", "gke-cost-analysis", "gke-cost-optimization",
    "bigquery-slot-cost-optimizer", "compute-engine-cost-optimization",
    "cloud-storage-cost-optimization", "google-cloud-waf-cost-optimization",
    "gcp-monitoring", "gcp-logging", "cost-report",
}


def _tools():
    return asyncio.run(agent.load_tools())


def _fake_agent(tools):
    return agent.build_agent(tools, model=GenericFakeChatModel(messages=iter([])))


def test_mcp_server_has_32_tools():
    names = {t.name for t in _tools()}
    assert len(names) == 32
    assert {"propose_change", "apply_change", "cancel_change", "get_recent_errors", "compare_months",
            "check_incident_status", "get_daily_spikes", "get_unlabeled_spend", "run_billing_query"} <= names


def test_project_is_self_contained():
    """The MCP server, skills and seed scripts all live in this folder."""
    cfg = agent.MCP_SERVERS[agent.SERVER]
    assert cfg["cwd"] == str(HERE) and cfg["command"] == sys.executable
    assert agent.SKILLS_DIR == HERE / "skills"
    for path in (HERE / "sre_mcp", HERE / "seed", HERE / "docker-compose.yml"):
        assert path.exists(), path


def test_skills_folder_has_10_skills():
    skills, error = _list_skills_with_errors(agent.make_backend(), "/skills/")
    assert error is None
    assert {s["name"] for s in skills} == EXPECTED_SKILLS


def test_apply_change_needs_approval():
    assert "apply_change" in agent.INTERRUPT_ON
    assert "propose_change" not in agent.INTERRUPT_ON
    graph = _fake_agent([])
    assert graph.checkpointer is not None
    hitl = [n for n in graph.nodes if "HumanInTheLoop" in n]
    assert hitl, "HumanInTheLoopMiddleware missing from the graph"


def test_no_write_delete_or_shell_tools(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "dummy-key-not-used")  # model is built, never called
    graph = agent.build_agent([], model=agent.MODEL)
    visible = set(graph.nodes["tools"].bound.tools_by_name)
    # Exclusion middleware hides blocked tools from the model; the middleware itself
    # only creates read-only file tools.
    assert visible <= set(agent.READ_ONLY_FS_TOOLS) | {"write_todos"}
    assert not visible & agent.BLOCKED_TOOLS


def test_env_is_git_ignored():
    result = subprocess.run(["git", "check-ignore", ".env"], cwd=HERE, capture_output=True, text=True)
    assert result.returncode == 0


class _FakeModel(GenericFakeChatModel):
    """Fake chat model that accepts tools (ignored)."""

    def bind_tools(self, tools, **kwargs):
        return self


class _BusyModel(_FakeModel):
    """Fake model that always fails like a busy Gemini."""

    def _generate(self, *args, **kwargs):
        raise RuntimeError("503 UNAVAILABLE: model is overloaded")


def test_backup_model_used_when_main_is_busy():
    assert agent.FALLBACK_MODELS, "no backup models configured"
    assert agent.MODEL not in agent.FALLBACK_MODELS
    backup = _FakeModel(messages=iter([AIMessage(content="answer from backup model")]))
    graph = agent.build_agent([], model=_BusyModel(messages=iter([])), fallbacks=[backup])
    result = graph.invoke({"messages": [{"role": "user", "content": "hi"}]},
                          {"configurable": {"thread_id": "fallback-test"}})
    assert result["messages"][-1].content == "answer from backup model"
