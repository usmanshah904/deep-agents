"""Terminal chat for the Deep Agents SRE agent.

Run:  .venv\\Scripts\\python.exe chat.py          (type "exit" to quit)
Each run keeps one conversation thread. apply_change always pauses for y/n.
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid

from langgraph.types import Command

from agent import FALLBACK_MODELS, MODEL, open_agent

RETRY_WAITS = [10, 30, 60]  # seconds between retries on Gemini 429/503
BUSY_MARKERS = ("429", "503", "RESOURCE_EXHAUSTED", "UNAVAILABLE", "overloaded", "high demand",
                "timed out", "timeout", "DEADLINE_EXCEEDED")
PIPED = not sys.stdin.isatty()


def ask(prompt: str) -> str:
    text = input(prompt)
    if PIPED:  # show scripted input so the transcript reads like a chat
        print(text)
    return text.strip()


def is_busy_error(exc: Exception) -> bool:
    return any(m.lower() in str(exc).lower() for m in BUSY_MARKERS)


class GeminiBusy(Exception):
    """Gemini stayed busy or rate-limited after all retries."""


_printed_calls: set[str] = set()


async def run_turn(agent, payload, config, log=print) -> list:
    """Stream one turn; report tool calls via `log`; return any pending interrupts."""
    interrupts = []
    async for update in agent.astream(payload, config, stream_mode="updates"):
        for node, data in update.items():
            if node == "__interrupt__":
                interrupts.extend(data)
                continue
            for msg in (data or {}).get("messages", []) if isinstance(data, dict) else []:
                for call in getattr(msg, "tool_calls", None) or []:
                    if call.get("id") in _printed_calls:
                        continue
                    _printed_calls.add(call.get("id"))
                    log(f"  -> {call['name']}({json.dumps(call['args'])[:120]})")
    return interrupts


async def run_with_retries(agent, payload, config, log=print) -> list:
    for attempt in range(len(RETRY_WAITS) + 1):
        try:
            return await run_turn(agent, payload, config, log)
        except Exception as exc:  # noqa: BLE001
            if not is_busy_error(exc):
                raise
            reason = str(exc).splitlines()[0][:160]
            if attempt == len(RETRY_WAITS):
                raise GeminiBusy(reason) from exc
            wait = RETRY_WAITS[attempt]
            log(f"  [Gemini busy/rate-limited: {reason}]")
            log(f"  [retrying in {wait}s ({attempt + 1}/{len(RETRY_WAITS)})]")
            await asyncio.sleep(wait)
            payload = None  # resume from the last saved step, do not resend the question
    return []


def decide(interrupt) -> dict:
    """Ask y/n for each paused tool call."""
    decisions = []
    for req in interrupt.value.get("action_requests", []):
        print("\n=== APPROVAL NEEDED ===")
        print(f"Tool: {req['name']}  Change ID: {req['args'].get('change_id', '?')}")
        answer = ""
        while answer not in ("y", "n"):
            answer = ask("Approve? y/n: ").lower()[:1]
        if answer == "y":
            decisions.append({"type": "approve"})
        else:
            decisions.append({"type": "reject", "message": "The user said NO at the terminal approval prompt. "
                              "Do not apply. Cancel the change with cancel_change."})
    return {"decisions": decisions}


async def answer_turn(agent, payload, config, decide_fn) -> None:
    """Run one user turn, including any approval pauses."""
    interrupts = await run_with_retries(agent, payload, config)
    while interrupts:
        resume = {i.id: decide_fn(i) for i in interrupts}
        cmd = Command(resume=resume if len(resume) > 1 else next(iter(resume.values())))
        interrupts = await run_with_retries(agent, cmd, config)


def last_answer(agent, config) -> str:
    msgs = agent.get_state(config).values.get("messages", [])
    for msg in reversed(msgs):
        if msg.type == "ai" and msg.text:
            return msg.text
    return "(no answer)"


async def main() -> None:
    config = {"configurable": {"thread_id": str(uuid.uuid4())}, "recursion_limit": 60}
    print(f"GCP SRE agent (Deep Agents + {MODEL}). Type 'exit' to quit.")
    print(f"Backup models if busy: {', '.join(FALLBACK_MODELS) or 'none'}")
    async with open_agent() as (agent, tools):
        print(f"Loaded {len(tools)} MCP tools.\n")
        while True:
            try:
                question = ask("\nYou: ")
            except EOFError:
                break
            if question.lower() in ("exit", "quit"):
                break
            if not question:
                continue
            payload = {"messages": [{"role": "user", "content": question}]}
            try:
                await answer_turn(agent, payload, config, decide)
            except GeminiBusy as exc:
                print(f"\n[Gemini is still busy or rate-limited ({exc}). Wait a few minutes, "
                      "then ask again.]")
                continue
            print(f"\nAgent: {last_answer(agent, config)}")


if __name__ == "__main__":
    asyncio.run(main())
