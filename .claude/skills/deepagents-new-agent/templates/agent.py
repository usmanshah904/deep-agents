"""The agent: Deep Agents + MCP tools + read-only skills + approval pauses.

Settings live in config.py, the system prompt in AGENT_RULES.md.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from deepagents import (
    FilesystemMiddleware,
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    create_deep_agent,
    register_harness_profile,
)
from deepagents.backends import CompositeBackend, FilesystemBackend, StateBackend
from dotenv import load_dotenv
from langchain.agents.middleware import ModelFallbackMiddleware
from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
from langgraph.checkpoint.memory import InMemorySaver
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

import config

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")

MODEL = os.getenv("AGENT_MODEL", config.MODEL)
FALLBACK_MODELS = [m.strip() for m in os.getenv("AGENT_FALLBACKS", ",".join(config.FALLBACKS)).split(",")
                   if m.strip() and m.strip() != MODEL]
MODEL_RETRIES = 1  # few retries per model, so a busy model hands over to the next one quickly

SKILLS_DIR = Path(config.SKILLS_DIR) if config.SKILLS_DIR else None
SYSTEM_PROMPT = (HERE / "AGENT_RULES.md").read_text(encoding="utf-8")

# Tools that must pause for a human "y/n" before they run.
INTERRUPT_ON = {name: {"allowed_decisions": ["approve", "reject"]} for name in config.APPROVE_TOOLS}

# Built-in file tools: read-only, only to read skills. No writes, no deletes, no shell.
READ_ONLY_FS_TOOLS = ["ls", "read_file", "glob", "grep"]
BLOCKED_TOOLS = frozenset({"write_file", "edit_file", "delete", "execute", "task"})

# Same tool server settings as an .mcp.json entry.
MCP_SERVERS = {
    name: {"transport": "stdio", **server, "env": {**os.environ, **server.get("env", {}), "GOOGLE_API_KEY": ""}}
    for name, server in config.MCP_SERVERS.items()
}

# Hide the general-purpose subagent ("task") and every write/shell tool for every provider we use.
for _provider in {m.split(":")[0] for m in [MODEL, *FALLBACK_MODELS] if ":" in m}:
    register_harness_profile(_provider, HarnessProfile(
        excluded_tools=BLOCKED_TOOLS,
        general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
    ))


def make_backend():
    """Virtual in-memory files, plus the skills folder (read-only tools) at /skills/."""
    if not SKILLS_DIR:
        return StateBackend()
    return CompositeBackend(default=StateBackend(),
                            routes={"/skills/": FilesystemBackend(root_dir=SKILLS_DIR, virtual_mode=True)})


def _model(model: str | BaseChatModel) -> BaseChatModel:
    return init_chat_model(model, max_retries=MODEL_RETRIES) if isinstance(model, str) else model


def build_agent(tools, model: str | BaseChatModel = MODEL, checkpointer=None,
                fallbacks: list[str | BaseChatModel] | None = None):
    """Build the agent. String models get the backup models unless `fallbacks` is given."""
    backend = make_backend()
    middleware = [FilesystemMiddleware(backend=backend, tools=READ_ONLY_FS_TOOLS)]
    if fallbacks is None:
        fallbacks = FALLBACK_MODELS if isinstance(model, str) else []
    if fallbacks:
        middleware.append(ModelFallbackMiddleware(*[_model(m) for m in fallbacks]))
    return create_deep_agent(
        model=_model(model),
        tools=tools,
        system_prompt=SYSTEM_PROMPT,
        skills=["/skills/"] if SKILLS_DIR else None,
        backend=backend,
        middleware=middleware,
        interrupt_on=INTERRUPT_ON or None,
        checkpointer=checkpointer or InMemorySaver(),
    )


async def load_tools():
    """Load all MCP tools (short-lived server per call; for tests and listing)."""
    if not MCP_SERVERS:
        return []
    return await MultiServerMCPClient(MCP_SERVERS).get_tools()


@asynccontextmanager
async def open_agent(model: str = MODEL):
    """Start the MCP server once for the whole chat and yield (agent, tools).

    The server's own log (stderr) goes to mcp_server.log, not the chat.
    """
    if not MCP_SERVERS:
        yield build_agent([], model=model), []
        return
    if len(MCP_SERVERS) > 1:
        tools = await load_tools()  # several servers: one short-lived session per call
        yield build_agent(tools, model=model), tools
        return
    cfg = next(iter(MCP_SERVERS.values()))
    params = StdioServerParameters(command=cfg["command"], args=cfg.get("args", []), cwd=cfg.get("cwd"), env=cfg["env"])
    with open(HERE / "mcp_server.log", "w", encoding="utf-8") as errlog:
        async with stdio_client(params, errlog=errlog) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            tools = await load_mcp_tools(session)
            yield build_agent(tools, model=model), tools
