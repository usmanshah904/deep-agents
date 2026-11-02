# {{NAME}}

{{DESCRIPTION}}

Built with LangChain Deep Agents (`deepagents`), created by the `deepagents-new-agent` skill.

## Setup (once)

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe copy_env.py "<path to an existing .env with the API key>"
git init
```

## Run

```powershell
.venv\Scripts\python.exe chat.py        # terminal chat, type "exit" to quit
.venv\Scripts\python.exe -m pytest -q   # setup tests, no API key needed
```

## Files

| File | What it is |
|---|---|
| `config.py` | Model, backup models, tool servers, skills folder, tools that need approval |
| `AGENT_RULES.md` | The system prompt: how the agent works and the approval rules |
| `agent.py` | Builds the agent (tools, skills, safety, approval pause) |
| `chat.py` | Terminal chat with y/n approval and retries when the model is busy |
| `tests/test_setup.py` | Tools load, skills found, approval configured, no write/shell tools, `.env` ignored |

## Safety

- Tools in `config.APPROVE_TOOLS` pause for y/n before they run.
- Built-in file tools are read-only (`ls`, `read_file`, `glob`, `grep`); no write, delete or shell tools.
- `.env` is git-ignored. Keys are never printed.
