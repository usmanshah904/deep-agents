---
name: deepagents-new-agent
description: >-
  Create a new agent project end to end with LangChain Deep Agents (deepagents)
  and Gemini or another LangChain model: agent.py, terminal chat with approval
  pauses, MCP tools, shared skills, safety settings, pinned venv, tests and README.
  Use when the user asks to start, scaffold, spin up or create a new agent, a
  Deep Agents project, or a copy of the SRE agent for another purpose. Don't use
  for changing an existing agent's prompt or tools only.
metadata:
  version: "1.0.0"
  based_on: "SRE Prototype / deep-agents (deepagents 0.7.29)"
---

# New Deep Agents project

Builds a working agent in a new folder from tested templates, then checks it.
The templates come from the SRE agent in `deep-agents/` and keep its safety rules.

## 1. Ask first (one short message, wait for answers)

1. **Name and folder**: for example `security-agent` in `C:\...\security-agent`.
2. **Job**: one or two sentences. What questions does it answer?
3. **Tools**: an MCP server (command, args, working folder, env), or none yet.
4. **Skills folder** (optional): an existing folder of `SKILL.md` skills to reuse (read-only).
5. **Actions that need human approval**: tool names that change things (for example
   `apply_change`, `send_email`). Everything that writes, deletes or spends must be here.
6. **Model**: default `google_genai:gemini-3.5-flash` with backups
   `google_genai:gemini-3.8-flash,google_genai:gemini-3.5-flash-lite`.
7. **API key source**: which existing `.env` holds the key (never ask the user to paste it).

Then show a 5-line plan and wait for approval before creating files.

## 2. Create the project

Run the scaffold script with the answers (paths are examples):

```bash
python .claude/skills/deepagents-new-agent/scripts/scaffold.py \
  --dest "C:/path/security-agent" --name "Security agent" \
  --description "Answers questions about IAM and firewall risks." \
  --model "google_genai:gemini-3.5-flash" \
  --fallbacks "google_genai:gemini-3.8-flash,google_genai:gemini-3.5-flash-lite" \
  --mcp-name "sec-mcp" --mcp-command "C:/path/.venv/Scripts/python.exe" \
  --mcp-args "server.py" --mcp-cwd "C:/path/server" --mcp-env "PROJECT=demo" \
  --skills-dir "C:/path/.claude/skills" \
  --approve "apply_change" --expect-tools 12 --expect-skills 4
```

- Leave out `--mcp-*` when there is no tool server yet, and `--skills-dir` when there are no skills.
- The script refuses a non-empty `--dest`. It writes: `agent.py`, `config.py`, `AGENT_RULES.md`,
  `chat.py`, `tests/test_setup.py`, `requirements.txt`, `.gitignore`, `README.md`, `copy_env.py`.

## 3. Fill in the rules

Edit `AGENT_RULES.md` (the system prompt) for the job: what to do, which tools to use when,
"copy numbers exactly from tools", and the approval flow for every tool in `--approve`.
Keep the safety section as it is.

## 4. Set up and check

```bash
cd <dest>
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe copy_env.py "<path to existing .env>"   # copies only the key line, prints nothing
git init
.venv\Scripts\python.exe -m pytest -q                            # no API key needed
```

- Use a **separate venv** per agent. Do not install deepagents into a venv that has google-adk.
- Then run one real question with `.venv\Scripts\python.exe chat.py` and check the answer.

## 5. Report

Tell the user in plain words: what was created, test results, model used, what is not tested yet.

## Rules (always)

- Never print, log or commit API keys. `.env` must be git-ignored (a test checks it).
- Every tool that changes something goes in `--approve` (pause for y/n before it runs).
- Built-in file tools stay read-only (`ls`, `read_file`, `glob`, `grep`); no `write_file`,
  `edit_file`, `delete`, `execute` or `task` subagent. Do not remove this.
- Pin versions. Deep Agents changes fast; see `reference/lessons.md` before changing APIs.
- Do not edit the folders that the tools or skills come from; reuse them read-only.
