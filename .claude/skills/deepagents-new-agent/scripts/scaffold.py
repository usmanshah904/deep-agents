"""Create a new Deep Agents project from the templates next to this script.

Example:
  python scaffold.py --dest C:/work/security-agent --name "Security agent" \
      --description "Answers questions about IAM risks." \
      --mcp-name sec-mcp --mcp-command C:/work/.venv/Scripts/python.exe --mcp-args server.py \
      --mcp-cwd C:/work/server --mcp-env PROJECT=demo --approve apply_change
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"
FILL = {"AGENT_RULES.md", "README.md"}  # files with {{PLACEHOLDERS}}
RENAME = {"gitignore": ".gitignore"}


def _list(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()] if value else []


def _config(a: argparse.Namespace) -> str:
    servers = {}
    if a.mcp_command:
        env = dict(item.split("=", 1) for item in _list(a.mcp_env))
        servers[a.mcp_name] = {"command": a.mcp_command, "args": a.mcp_args.split() if a.mcp_args else [],
                               **({"cwd": a.mcp_cwd} if a.mcp_cwd else {}), "env": env}
    return f'''"""Agent settings. Edit here; agent.py reads them."""

NAME = {a.name!r}

# LangChain model strings ("provider:model"). Backups are tried in order when the main one
# fails (rate limit 429, busy 503). Override with AGENT_MODEL / AGENT_FALLBACKS in .env.
MODEL = {a.model!r}
FALLBACKS = {_list(a.fallbacks)!r}

# Tool servers (MCP over stdio), same fields as an .mcp.json entry. Empty = no tools yet.
MCP_SERVERS = {servers!r}

# Folder of SKILL.md skills, mounted read-only at /skills/. None = no skills.
SKILLS_DIR = {a.skills_dir or None!r}

# Tools that must pause for a human y/n before they run (anything that changes, sends or spends).
APPROVE_TOOLS = {_list(a.approve)!r}

# Expected counts, checked by tests/test_setup.py. None = do not check.
EXPECT_TOOLS = {a.expect_tools!r}
EXPECT_SKILLS = {a.expect_skills!r}
'''


def main() -> None:
    p = argparse.ArgumentParser(description="Create a new Deep Agents project.")
    p.add_argument("--dest", required=True, help="new project folder (must be empty or not exist)")
    p.add_argument("--name", required=True)
    p.add_argument("--description", default="A Deep Agents agent.")
    p.add_argument("--model", default="google_genai:gemini-3.5-flash")
    p.add_argument("--fallbacks", default="google_genai:gemini-3.8-flash,google_genai:gemini-3.5-flash-lite")
    p.add_argument("--mcp-name", default="tools")
    p.add_argument("--mcp-command", default="", help="command that starts the MCP server (stdio)")
    p.add_argument("--mcp-args", default="", help="space-separated arguments")
    p.add_argument("--mcp-cwd", default="")
    p.add_argument("--mcp-env", default="", help="comma list KEY=VALUE (no secrets)")
    p.add_argument("--skills-dir", default="")
    p.add_argument("--approve", default="", help="comma list of tool names that need approval")
    p.add_argument("--expect-tools", type=int, default=None)
    p.add_argument("--expect-skills", type=int, default=None)
    a = p.parse_args()

    dest = Path(a.dest)
    if dest.exists() and any(dest.iterdir()):
        sys.exit(f"{dest} is not empty. Pick a new folder.")
    if a.skills_dir and not Path(a.skills_dir).is_dir():
        sys.exit(f"Skills folder not found: {a.skills_dir}")
    dest.mkdir(parents=True, exist_ok=True)

    values = {"{{NAME}}": a.name, "{{DESCRIPTION}}": a.description,
              "{{APPROVE_TOOLS}}": ", ".join(_list(a.approve)) or "none yet"}
    for src in TEMPLATES.rglob("*"):
        if src.is_dir() or "__pycache__" in src.parts:
            continue
        rel = src.relative_to(TEMPLATES)
        out = dest / rel.parent / RENAME.get(rel.name, rel.name)
        out.parent.mkdir(parents=True, exist_ok=True)
        if rel.name in FILL:
            text = src.read_text(encoding="utf-8")
            for k, v in values.items():
                text = text.replace(k, v)
            out.write_text(text, encoding="utf-8")
        else:
            shutil.copyfile(src, out)
    (dest / "config.py").write_text(_config(a), encoding="utf-8")

    print(f"Created {a.name} in {dest}")
    for f in sorted(x.relative_to(dest) for x in dest.rglob("*") if x.is_file()):
        print("  ", f)
    print("Next: create the venv, install requirements, copy the key with copy_env.py, git init, run pytest.")


if __name__ == "__main__":
    main()
