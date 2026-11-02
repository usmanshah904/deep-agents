# Lessons from the SRE agent (deepagents 0.7.29)

Read before changing agent.py or upgrading versions.

## Deep Agents API (checked in the 0.7.29 source)
- `create_deep_agent(model, tools, system_prompt=, skills=, memory=, backend=, middleware=,
  interrupt_on=, checkpointer=, ...)`.
- **Skills**: `skills=["/skills/"]` are paths in the backend, not on disk. Mount a disk folder
  with `CompositeBackend(default=StateBackend(), routes={"/skills/": FilesystemBackend(root_dir=..., virtual_mode=True)})`.
  Only each SKILL.md's frontmatter goes into the prompt at start (progressive disclosure);
  the agent reads the full file with `read_file` when needed.
- **Approval**: `interrupt_on={"tool": {"allowed_decisions": ["approve", "reject"]}}` adds
  `HumanInTheLoopMiddleware`. It needs a checkpointer. The run pauses with `__interrupt__`;
  resume with `Command(resume={"decisions": [{"type": "approve"}]})` (one decision per paused call,
  in order; reject can carry a `message`).
- **Remove dangerous built-ins**: pass `FilesystemMiddleware(backend=..., tools=["ls","read_file","glob","grep"])`
  in `middleware=` (it replaces the default by name; `read_file` is required), and register a
  `HarnessProfile(excluded_tools=..., general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False))`
  for the model provider (for example `"google_genai"`) to drop `task`, `write_file`, `edit_file`,
  `delete`, `execute`. The test `test_no_write_delete_or_shell_tools` checks this.
- **Backup models**: `ModelFallbackMiddleware(model_a, model_b)` from `langchain.agents.middleware`.
  Build models with `init_chat_model(spec, max_retries=1)`; the default 6 retries makes fallback slow.

## MCP tools
- `langchain-mcp-adapters` `MultiServerMCPClient(...).get_tools()` opens a new server per tool
  call. For a chat, keep one session: `stdio_client(params, errlog=file)` + `ClientSession` +
  `load_mcp_tools(session)`. `errlog=` keeps the server's log lines out of the chat.
- The MCP server can run in a different venv (for example one with mcp 2.x); only stdio connects them.

## Gemini (free tier)
- Limits are per model per day (`GenerateRequestsPerDayPerProjectPerModel-FreeTier`). One demo run
  of ~3 questions used most of a day's quota for one model. Backup models each have their own quota.
- 503 "model busy" happens at peak times. Retry with waits, then fall back.
- Small models sometimes add up numbers themselves: keep "copy numbers exactly from tools" in the rules.

## Windows
- Use a separate venv per agent; deepagents conflicts with google-adk.
- Heredocs with `\a`, `\S` in Python strings break Windows paths: use raw strings.
- When a terminal panel cancels a long-running start, run it with `Start-Process powershell -ArgumentList '-NoExit', ...`.

## Optional extras (not in the templates)
- Saved chats: `langgraph-checkpoint-sqlite` `AsyncSqliteSaver.from_conn_string("chats.sqlite")`
  as the checkpointer; Postgres saver for many users.
- Web chat with Approve/Reject buttons: see `deep-agents/dashboard/app.py` (FastAPI) in the SRE prototype.
