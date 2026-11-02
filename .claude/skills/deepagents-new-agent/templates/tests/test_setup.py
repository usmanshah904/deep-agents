"""Setup checks that need no API key and no network (the MCP server, if any, runs locally)."""

import asyncio
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel  # noqa: E402
from langchain_core.messages import AIMessage  # noqa: E402

import agent  # noqa: E402
import config  # noqa: E402
from deepagents.middleware.skills import _list_skills_with_errors  # noqa: E402


class _FakeModel(GenericFakeChatModel):
    """Fake chat model that accepts tools (ignored)."""

    def bind_tools(self, tools, **kwargs):
        return self


class _BusyModel(_FakeModel):
    def _generate(self, *args, **kwargs):
        raise RuntimeError("503 UNAVAILABLE: model is overloaded")


def test_tools_load():
    tools = asyncio.run(agent.load_tools())
    if config.EXPECT_TOOLS is not None:
        assert len(tools) == config.EXPECT_TOOLS
    names = {t.name for t in tools}
    assert set(config.APPROVE_TOOLS) <= names or not config.MCP_SERVERS, "approval tool names must exist"


def test_skills_found():
    if not agent.SKILLS_DIR:
        return
    skills, error = _list_skills_with_errors(agent.make_backend(), "/skills/")
    assert error is None
    if config.EXPECT_SKILLS is not None:
        assert len(skills) == config.EXPECT_SKILLS


def test_approval_pause_configured():
    assert set(agent.INTERRUPT_ON) == set(config.APPROVE_TOOLS)
    graph = agent.build_agent([], model=_FakeModel(messages=iter([])))
    assert graph.checkpointer is not None
    if config.APPROVE_TOOLS:
        assert any("HumanInTheLoop" in n for n in graph.nodes)


def test_no_write_delete_or_shell_tools(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "dummy-key-not-used")  # model is built, never called
    graph = agent.build_agent([], model=agent.MODEL)
    visible = set(graph.nodes["tools"].bound.tools_by_name)
    assert visible <= set(agent.READ_ONLY_FS_TOOLS) | {"write_todos"}
    assert not visible & agent.BLOCKED_TOOLS


def test_backup_model_used_when_main_is_busy():
    backup = _FakeModel(messages=iter([AIMessage(content="answer from backup")]))
    graph = agent.build_agent([], model=_BusyModel(messages=iter([])), fallbacks=[backup])
    result = graph.invoke({"messages": [{"role": "user", "content": "hi"}]}, {"configurable": {"thread_id": "t"}})
    assert result["messages"][-1].content == "answer from backup"


def test_env_is_git_ignored():
    result = subprocess.run(["git", "check-ignore", ".env"], cwd=HERE, capture_output=True, text=True)
    assert result.returncode == 0, "run 'git init' and keep .env in .gitignore"
