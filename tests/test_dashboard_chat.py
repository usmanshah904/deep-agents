"""Dashboard chat checks with a fake model (no Gemini key, no network)."""

import json
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "dashboard"))

from fastapi.testclient import TestClient  # noqa: E402
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel  # noqa: E402
from langchain_core.messages import AIMessage  # noqa: E402
from langchain_core.tools import tool  # noqa: E402
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver  # noqa: E402

import agent  # noqa: E402
import app as dashboard  # noqa: E402

CHANGE_ID = "chg-abc123"


class _FakeModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def _iso(minutes_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _tools(applied: list, changes: list):
    @tool
    def apply_change(change_id: str) -> str:
        """Fake apply_change that only records the call."""
        applied.append(change_id)
        return f"{change_id} applied"

    @tool
    def propose_change(action: str, target: str) -> str:
        """Fake propose_change."""
        return json.dumps({"status": "ok", "change": {"id": CHANGE_ID, "status": "proposed"}})

    @tool
    def list_changes(limit: int = 20) -> str:
        """Fake change history."""
        return json.dumps({"status": "ok", "total": len(changes), "counts": {}, "changes": changes})

    @tool
    def get_inventory() -> str:
        """Fake inventory."""
        return json.dumps({"status": "ok", "vms": [], "buckets": []})

    return [apply_change, propose_change, list_changes, get_inventory]


def _client(tmp_path, replies, applied=None, changes=None, db=None):
    applied = [] if applied is None else applied
    tools = _tools(applied, changes or [])

    @asynccontextmanager
    async def fake_agent():
        model = _FakeModel(messages=iter(replies))
        if db is None:
            yield agent.build_agent(tools, model=model), tools
        else:
            async with AsyncSqliteSaver.from_conn_string(str(db)) as saver:
                yield agent.build_agent(tools, model=model, checkpointer=saver), tools

    return TestClient(dashboard.create_app(fake_agent, links_file=tmp_path / "links.json"))


def _apply_replies():
    return [AIMessage(content="", tool_calls=[{"name": "apply_change", "args": {"change_id": CHANGE_ID}, "id": "call-1"}]),
            AIMessage(content="Done.")]


def _ask(c):
    r = c.post("/api/chat", json={"message": f"approve {CHANGE_ID}"}).json()
    assert r["approval"] == {"change_id": CHANGE_ID, "tool": "apply_change"}
    return r["thread_id"]


# ---------- final Approve / Reject (the pause before apply_change) ----------

def test_apply_change_waits_for_click_and_wrong_id_is_refused(tmp_path):
    applied = []
    with _client(tmp_path, _apply_replies(), applied) as c:
        thread = _ask(c)
        assert applied == []  # paused, nothing ran
        assert c.post("/api/chat", json={"message": "hi", "thread_id": thread}).status_code == 409
        wrong = {"thread_id": thread, "change_id": "chg-999999", "decision": "approve"}
        assert c.post("/api/chat/approve", json=wrong).status_code == 409
        assert applied == []


def test_approve_click_runs_the_change_once(tmp_path):
    applied = []
    with _client(tmp_path, _apply_replies(), applied) as c:
        thread = _ask(c)
        r = c.post("/api/chat/approve", json={"thread_id": thread, "change_id": CHANGE_ID, "decision": "approve"}).json()
        assert applied == [CHANGE_ID]
        assert r["approval"] is None and r["answer"] == "Done."


def test_reject_click_never_runs_the_change(tmp_path):
    applied = []
    with _client(tmp_path, _apply_replies(), applied) as c:
        thread = _ask(c)
        r = c.post("/api/chat/approve", json={"thread_id": thread, "change_id": CHANGE_ID, "decision": "reject"}).json()
        assert applied == []
        assert r["approval"] is None
        assert c.post("/api/chat/approve", json={"thread_id": thread, "change_id": CHANGE_ID,
                                                 "decision": "approve"}).status_code == 409


# ---------- saved chats and the change -> chat link ----------

def test_chat_is_saved_and_linked_to_the_change_it_proposed(tmp_path):
    db = tmp_path / "chats.sqlite"
    replies = [AIMessage(content="", tool_calls=[{"name": "propose_change", "args": {"action": "restart_vm", "target": "db-proxy"},
                                                  "id": "call-1"}]),
               AIMessage(content=f"Approve {CHANGE_ID}?")]
    with _client(tmp_path, replies, db=db) as c:
        thread = c.post("/api/chat", json={"message": "fix db-proxy"}).json()["thread_id"]
        assert c.get("/api/changes").json()["chat_links"] == {CHANGE_ID: thread}

    # A new dashboard process (restart) still has the conversation.
    with _client(tmp_path, [], db=db) as c:
        r = c.get(f"/api/chat/thread/{thread}").json()
        assert [m["role"] for m in r["messages"]] == ["user", "agent"]
        assert r["messages"][0]["text"] == "fix db-proxy"
        assert r["messages"][1]["text"] == f"Approve {CHANGE_ID}?"
        assert r["messages"][1]["steps"][0].startswith("-> propose_change(")


# ---------- Approve / Cancel buttons for waiting (older) changes ----------

def _change(minutes_ago: float, status: str = "proposed") -> dict:
    return {"id": CHANGE_ID, "status": status, "summary": "Restart VM db-proxy", "proposed_at": _iso(minutes_ago)}


def test_old_change_approve_asks_agent_to_recheck_first(tmp_path):
    applied = []
    replies = [AIMessage(content="The incident is already resolved, so this is no longer needed. I recommend cancelling it.")]
    with _client(tmp_path, replies, applied, changes=[_change(3 * 24 * 60)]) as c:
        r = c.post("/api/chat/change", json={"change_id": CHANGE_ID, "action": "approve"}).json()
        assert applied == [] and r["approval"] is None  # the agent did not apply
        shown = c.get(f"/api/chat/thread/{r['thread_id']}").json()["messages"]
        assert shown[0] == {"role": "user", "text": f"Clicked Approve for {CHANGE_ID}", "click": True}


def test_action_messages():
    old, new = _change(3 * 24 * 60), _change(2)
    assert "re-check" in dashboard._action_message(old, "approve")
    assert "3 days ago" in dashboard._action_message(old, "approve")
    assert dashboard._action_message(new, "approve") == f"Approve {CHANGE_ID}."
    assert "re-check" in dashboard._action_message(new, "approve", has_context=False)  # new chat: no context
    assert "cancel_change" in dashboard._action_message(old, "cancel")


def test_buttons_refused_for_changes_not_waiting(tmp_path):
    with _client(tmp_path, [], changes=[_change(5, status="applied")]) as c:
        assert c.post("/api/chat/change", json={"change_id": CHANGE_ID, "action": "approve"}).status_code == 409
        assert c.post("/api/chat/change", json={"change_id": "chg-000000", "action": "cancel"}).status_code == 404
        assert c.post("/api/chat/change", json={"change_id": CHANGE_ID, "action": "delete"}).status_code == 400
