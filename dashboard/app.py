"""Web dashboard + chat for the Deep Agents SRE agent.

Copied from claude-desktop-agent/dashboard and changed to:
  - read every number through the same gcp-sre-mcp MCP tools the agent uses
  - add a Chat page: ask the agent, and approve or reject changes with buttons

Run (from deep-agents):  .venv\\Scripts\\python.exe dashboard\\app.py  ->  http://127.0.0.1:8060
"""

from __future__ import annotations

import asyncio
import os
import json
import sys
import uuid
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import uvicorn  # noqa: E402
import yaml  # noqa: E402
from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from langgraph.types import Command  # noqa: E402
from pydantic import BaseModel  # noqa: E402

import agent as sre_agent  # noqa: E402
from chat import GeminiBusy, run_with_retries  # noqa: E402

STATIC = HERE / "static"
HISTORY_DB = HERE.parent / "chat_history.sqlite"  # saved conversations (git-ignored)
LINKS_FILE = HERE.parent / "chat_links.json"      # change ID -> chat that proposed it (git-ignored)
RECHECK_AFTER_MINUTES = 10  # Approve on a change older than this asks the agent to re-check first
TOOL_GROUPS = [("cost", 20), ("observability", 7), ("changes", 5)]  # order of tools on the MCP server
PORT = int(os.getenv("DASHBOARD_PORT", "8060"))


class ChatIn(BaseModel):
    message: str
    thread_id: str | None = None


class ChangeActionIn(BaseModel):
    change_id: str
    action: str  # "approve" or "cancel"
    thread_id: str | None = None


class ApprovalIn(BaseModel):
    thread_id: str
    change_id: str
    decision: str  # "approve" or "reject"


REJECT_MESSAGE = ("The user clicked Reject in the dashboard. Do not apply. "
                  "Cancel the change with cancel_change and say so.")


def create_app(agent_cm=None, links_file: Path = LINKS_FILE) -> FastAPI:
    """`agent_cm` yields (agent, tools); tests pass a fake one. Default: the real agent with saved chats."""
    agent_cm = agent_cm or (lambda: sre_agent.open_agent(history_db=HISTORY_DB))
    links = _Links(links_file)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with agent_cm() as (graph, tools):
            app.state.agent = graph
            app.state.tools = {t.name: t for t in tools}
            app.state.tool_order = [t.name for t in tools]
            app.state.turn_lock = asyncio.Lock()
            yield

    app = FastAPI(title="GCP SRE Agent dashboard (Deep Agents)", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.middleware("http")
    async def no_cache(request, call_next):
        # Local tool: always serve the latest files and data.
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-cache"
        return response

    async def tool(name: str, **args) -> dict:
        """Call one MCP tool and return its JSON result."""
        result = await app.state.tools[name].ainvoke(args)
        if isinstance(result, tuple):  # (content, artifact)
            result = result[0]
        if isinstance(result, list):
            result = "".join(p.get("text", "") for p in result if isinstance(p, dict))
        if isinstance(result, str):
            try:
                return json.loads(result)
            except json.JSONDecodeError:
                return {"status": "error", "message": result}
        return result

    async def gather(calls: dict) -> dict:
        keys = list(calls)
        values = await asyncio.gather(*calls.values())
        return dict(zip(keys, values))

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.get("/api/cost")
    async def cost() -> dict:
        """Every cost tool result, plus where the cost data comes from."""
        data = await gather({
            "summary": tool("get_cost_summary"),
            "by_service": tool("get_cost_by_service"),
            "by_project": tool("get_cost_by_project"),
            "compare": tool("compare_months"),
            "gke_clusters": tool("get_gke_cost_by_cluster"),
            "gke_namespaces": tool("get_gke_cost_by_namespace"),
            "gke_workloads": tool("get_gke_top_workloads", limit=50),
            "gke_overprovisioned": tool("get_gke_overprovisioned_workloads"),
            "bigquery": tool("get_bigquery_expensive_queries", limit=20),
            "vms": tool("get_compute_cost_by_instance", limit=50),
            "vm_waste": tool("get_compute_waste"),
            "commitments": tool("get_compute_commitment_coverage"),
            "buckets": tool("get_storage_cost_by_bucket", limit=50),
            "storage_waste": tool("get_storage_waste"),
            "savings": tool("estimate_savings"),
        })
        return {**data, "source": _cost_source()}

    @app.get("/api/observability")
    async def observability(hours: int = 24) -> dict:
        """Monitoring and logging overview from floci-gcp."""
        data = await gather({
            "metrics": tool("list_metrics"),
            "vm_cpu": tool("get_resource_utilization", kind="vm", metric="cpu", hours=hours),
            "vm_memory": tool("get_resource_utilization", kind="vm", metric="memory", hours=hours),
            "gke_cpu": tool("get_resource_utilization", kind="gke", metric="cpu", hours=hours),
            "gke_memory": tool("get_resource_utilization", kind="gke", metric="memory", hours=hours),
            "errors": tool("get_recent_errors", hours=hours, limit=20),
            "log_summary": tool("get_log_summary", hours=hours),
            "warnings_and_errors": tool("search_logs", severity="WARNING", hours=hours, limit=2000),
            "resolutions": tool("search_logs", query="RESOLVED:", hours=hours, limit=50),
        })
        project = data["log_summary"].get("project") or sre_agent.MCP_SERVERS[sre_agent.SERVER]["env"]["GCP_PROJECT"]
        return {"project": project, "hours": hours, **data}

    @app.get("/api/timeseries")
    async def timeseries(metric_type: str, resource: str | None = None, hours: int = 24) -> dict:
        return await tool("get_metric_timeseries", metric_type=metric_type, resource_name=resource, hours=hours)

    @app.get("/api/logs")
    async def logs(query: str | None = None, severity: str | None = None, resource: str | None = None,
                   hours: int = 24, limit: int = 100) -> dict:
        return await tool("search_logs", query=query or None, severity=severity or None,
                          resource=resource or None, hours=hours, limit=limit)

    @app.get("/api/changes")
    async def changes_history() -> dict:
        """Change history and live inventory. Changes are applied only through the chat approval."""
        data = await gather({"history": tool("list_changes", limit=100), "inventory": tool("get_inventory")})
        return {**data, "chat_links": links.all()}

    @app.get("/api/agent")
    def agent_info() -> dict:
        """Skills and tools the agent has, read from the shared folders and the MCP server."""
        skills = [_skill_info(p) for p in sorted(sre_agent.SKILLS_DIR.glob("*/SKILL.md"))]
        ends, total = [], 0
        for group, size in TOOL_GROUPS:
            total += size
            ends.append((group, total))
        tools = [
            {
                "name": name,
                "group": next((g for g, end in ends if i < end), "other"),
                "description": (app.state.tools[name].description or "").strip().splitlines()[0]
                if app.state.tools[name].description else "",
            }
            for i, name in enumerate(app.state.tool_order)
        ]
        return {"skills": skills, "tools": tools,
                "model": sre_agent.MODEL.split(":")[-1], "cost_source": _cost_source(),
                "fallbacks": [m.split(":")[-1] for m in sre_agent.FALLBACK_MODELS]}

    # ---------- Chat ----------

    async def run(thread_id: str, payload) -> dict:
        graph = app.state.agent
        config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 60}
        before = len((await graph.aget_state(config)).values.get("messages", []))
        steps: list[str] = []
        error = None
        async with app.state.turn_lock:  # one agent turn at a time
            try:
                await run_with_retries(graph, payload, config, log=lambda line: steps.append(line.strip()))
            except GeminiBusy as exc:
                error = f"Gemini is still busy or out of free quota ({exc}). Wait a few minutes and ask again."
        state = await graph.aget_state(config)
        new = state.values.get("messages", [])[before:]
        for change_id in _proposed_ids(new):
            links.set(change_id, thread_id)
        answer = "\n\n".join(m.text for m in new if m.type == "ai" and m.text)
        return {"thread_id": thread_id, "answer": answer, "steps": steps,
                "approval": _pending_approval(state), "error": error}

    @app.post("/api/chat")
    async def chat(body: ChatIn) -> dict:
        if not body.message.strip():
            raise HTTPException(400, "Empty message.")
        thread_id = body.thread_id or str(uuid.uuid4())
        state = await app.state.agent.aget_state({"configurable": {"thread_id": thread_id}})
        if _pending_approval(state):
            raise HTTPException(409, "A change is waiting for Approve or Reject. Click one first.")
        return await run(thread_id, {"messages": [{"role": "user", "content": body.message}]})

    @app.post("/api/chat/approve")
    async def approve(body: ApprovalIn) -> dict:
        if body.decision not in ("approve", "reject"):
            raise HTTPException(400, "decision must be 'approve' or 'reject'.")
        state = await app.state.agent.aget_state({"configurable": {"thread_id": body.thread_id}})
        pending = _pending_approval(state)
        if not pending:
            raise HTTPException(409, "Nothing is waiting for approval.")
        if pending["change_id"] != body.change_id:
            raise HTTPException(409, f"The waiting change is {pending['change_id']}, not {body.change_id}.")
        # One decision per paused call. Only the clicked change ID can be approved.
        decisions, approved = [], False
        for intr in state.interrupts:
            for req in intr.value.get("action_requests", []):
                ok = body.decision == "approve" and req["args"].get("change_id") == body.change_id and not approved
                approved = approved or ok
                decisions.append({"type": "approve"} if ok else {"type": "reject", "message": REJECT_MESSAGE})
        return await run(body.thread_id, Command(resume={"decisions": decisions}))

    @app.get("/api/chat/thread/{thread_id}")
    async def chat_thread(thread_id: str) -> dict:
        """A saved conversation, ready to show on the Chat page."""
        state = await app.state.agent.aget_state({"configurable": {"thread_id": thread_id}})
        return {"thread_id": thread_id, "messages": _display(state.values.get("messages", [])),
                "approval": _pending_approval(state)}

    @app.post("/api/chat/change")
    async def change_action(body: ChangeActionIn) -> dict:
        """Approve or Cancel button for a waiting change (also for older changes)."""
        if body.action not in ("approve", "cancel"):
            raise HTTPException(400, "action must be 'approve' or 'cancel'.")
        history = await tool("list_changes", limit=1000)
        change = next((c for c in history.get("changes", []) if c["id"] == body.change_id), None)
        if not change:
            raise HTTPException(404, f"No change with ID {body.change_id}.")
        if change["status"] != "proposed":
            raise HTTPException(409, f"{body.change_id} is '{change['status']}', not waiting for approval.")
        known_thread = body.thread_id or links.get(body.change_id)
        thread_id = known_thread or str(uuid.uuid4())
        state = await app.state.agent.aget_state({"configurable": {"thread_id": thread_id}})
        if _pending_approval(state):
            raise HTTPException(409, "A change is waiting for the final Approve or Reject. Click one first.")
        message = _action_message(change, body.action, has_context=known_thread is not None)
        return await run(thread_id, {"messages": [{"role": "user", "content": message}]})

    return app


def _cost_source() -> str:
    env = sre_agent.MCP_SERVERS[sre_agent.SERVER]["env"]
    return "billing export (BigQuery)" if env["COST_DATA_SOURCE"] == "bigquery" else "mock data"


class _Links:
    """Which chat proposed which change. A small JSON file."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def all(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def get(self, change_id: str) -> str | None:
        return self.all().get(change_id)

    def set(self, change_id: str, thread_id: str) -> None:
        data = self.all()
        data[change_id] = thread_id
        self.path.write_text(json.dumps(data, indent=1), encoding="utf-8")


def _proposed_ids(messages) -> list[str]:
    """Change IDs created by successful propose_change calls in these messages."""
    ids = []
    for m in messages:
        if m.type == "tool" and m.name == "propose_change":
            text = m.content if isinstance(m.content, str) else "".join(
                p.get("text", "") for p in m.content if isinstance(p, dict))
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                continue
            if data.get("status") == "ok":
                ids.append(data["change"]["id"])
    return ids


def _age(iso: str | None) -> tuple[float, str]:
    """Minutes since `iso`, and the same in words."""
    try:
        then = datetime.strptime(iso or "", "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return 0.0, "some time"
    minutes = (datetime.now(timezone.utc) - then).total_seconds() / 60
    if minutes < 60:
        return minutes, f"{int(minutes)} minutes"
    if minutes < 48 * 60:
        return minutes, f"{int(minutes // 60)} hours"
    return minutes, f"{int(minutes // 1440)} days"


def _action_message(change: dict, action: str, has_context: bool = True) -> str:
    """What a button click says to the agent, in the user's name.

    A new chat (no context) always gets the full details and a re-check request."""
    cid = change["id"]
    if action == "cancel":
        return f"I clicked Cancel for {cid}. Cancel it with cancel_change."
    minutes, words = _age(change.get("proposed_at"))
    if minutes < RECHECK_AFTER_MINUTES and has_context:
        return f"Approve {cid}."
    return (f"I clicked Approve for {cid} ({change.get('summary', '')}), which was proposed {words} ago. "
            "Before applying, re-check that it is still needed and that the resource still matches its "
            "'before' state (rule 8). Then apply it, or tell me why not and what you recommend.")


def _display(messages) -> list[dict]:
    """Saved agent messages -> the chat bubbles the page shows."""
    out, steps = [], []
    for m in messages:
        if m.type == "human":
            if m.text.startswith("I clicked "):  # a button click, shown short
                out.append({"role": "user", "text": "Clicked " + m.text[len("I clicked "):].split(" (")[0].split(".")[0],
                            "click": True})
            else:
                out.append({"role": "user", "text": m.text})
        elif m.type == "ai":
            for call in m.tool_calls or []:
                steps.append(f"-> {call['name']}({json.dumps(call['args'])[:120]})")
            if m.text:
                out.append({"role": "agent", "text": m.text, "steps": steps})
                steps = []
    if steps:
        out.append({"role": "agent", "text": "", "steps": steps})
    return out


def _pending_approval(state) -> dict | None:
    """The apply_change call waiting for the user's click, if any."""
    for intr in getattr(state, "interrupts", ()) or ():
        for req in (intr.value or {}).get("action_requests", []):
            if req.get("name") == "apply_change":
                return {"change_id": req["args"].get("change_id", ""), "tool": req["name"]}
    return None


def _skill_info(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    front = yaml.safe_load(text.split("---")[1]) if text.startswith("---") else {}
    description = " ".join(str(front.get("description", "")).split())
    publisher = (front.get("metadata") or {}).get("publisher", "")
    return {
        "name": front.get("name", path.parent.name),
        "source": "Custom" if publisher == "custom" else "Google",
        "description": description.split(". ")[0].rstrip(".") + ".",
    }


app = create_app()

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT)
