"""Checks that everything is set up, before you chat. Needs no AI quota.

Run: .venv\\Scripts\\python.exe check.py     (exit code 0 = ready)
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import urllib.error
import urllib.request

MIN_PYTHON = (3, 12)
results: list[tuple[str, str, str]] = []  # (OK | WARN | FAIL, check, detail)


def report(status: str, name: str, detail: str = "") -> None:
    results.append((status, name, detail))
    print(f"[{status:4}] {name}" + (f": {detail}" if detail else ""), flush=True)


def _get(url: str, timeout: float = 5) -> int:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code


def main() -> int:
    ok_python = sys.version_info >= MIN_PYTHON
    report("OK" if ok_python else "FAIL", "Python", f"{sys.version.split()[0]} (need {'.'.join(map(str, MIN_PYTHON))}+)")
    try:
        import agent  # loads .env
    except ImportError as exc:
        report("FAIL", "Packages", f"{exc}. Run: pip install -r requirements.txt")
        return 1
    report("OK", "Packages", "deepagents, langchain, mcp installed")

    provider = agent.MODEL.split(":", 1)[0]
    key = {"google_genai": "GOOGLE_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY",
           "openrouter": "OPENROUTER_API_KEY"}.get(provider)
    if key and not os.getenv(key):
        report("FAIL", "Model key", f"{key} is not set in .env (copy .env.example to .env)")
    else:
        report("OK", "Model key", f"{key or 'provider key'} is set for {agent.MODEL}")

    env = agent.MCP_SERVERS[agent.SERVER]["env"]
    floci = env["OBS_API_URL"]
    try:
        _get(floci)
        report("OK", "floci emulator", floci)
        floci_up = True
    except OSError:
        report("FAIL", "floci emulator", f"not reachable at {floci}. Start Docker Desktop, then: docker compose up -d")
        floci_up = False

    if floci_up:
        project = env["GCP_PROJECT"]
        try:
            vms = json.load(urllib.request.urlopen(f"{floci}/compute/v1/projects/{project}/aggregated/instances", timeout=10))
            count = sum(len(v.get("instances", [])) for v in vms.get("items", {}).values())
        except (OSError, ValueError):
            count = 0
        report("OK" if count else "FAIL", "Sample cloud (VMs, metrics, logs)",
               f"{count} VMs" if count else "empty. Run: python -m seed.seed_floci")
        if env["COST_DATA_SOURCE"] == "bigquery":
            p, d, t = env["BQ_BILLING_TABLE"].split(".")
            status = _get(f"{env['BQ_API_URL']}/bigquery/v2/projects/{p}/datasets/{d}/tables/{t}", timeout=10)
            report("OK" if status == 200 else "FAIL", "Billing export table",
                   env["BQ_BILLING_TABLE"] if status == 200 else "missing. Run: python -m seed.seed_billing")
    if env["COST_DATA_SOURCE"] != "bigquery":
        report("WARN", "Billing data", "COST_DATA_SOURCE=mock: sample JSON files, not the BigQuery export")

    try:
        tools = asyncio.run(agent.load_tools())
        report("OK" if len(tools) == 32 else "WARN", "MCP server gcp-sre-mcp", f"{len(tools)} tools")
    except Exception as exc:  # noqa: BLE001
        report("FAIL", "MCP server gcp-sre-mcp", str(exc)[:200])
    skills = sorted(p.parent.name for p in agent.SKILLS_DIR.glob("*/SKILL.md"))
    report("OK" if skills else "FAIL", "Skills", f"{len(skills)} in skills/")

    failed = [r for r in results if r[0] == "FAIL"]
    print("\nReady. Run: python chat.py   or   python dashboard/app.py" if not failed
          else f"\n{len(failed)} problem(s) to fix first (see above).")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
