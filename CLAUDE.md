# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install in editable mode with dev dependencies
uv pip install -e ".[dev]"

# Run tests
pytest
pytest tests/test_commands.py          # single test file
pytest tests/test_loop_simple.py -k test_name  # single test

# Lint and format
ruff check nanobot
ruff format nanobot

# Run locally
nanobot onboard          # initialize workspace (~/.nanobot/)
nanobot agent            # interactive REPL
nanobot gateway          # HTTP gateway server on port 18790
nanobot status           # check system status

## Architecture

Nanobot is an ultra-lightweight personal AI assistant framework. The core flow is:

**Channels → Message Bus → Agent Loop → Tools/LLM → Channels**

1. **Channels** (`nanobot/channels/`) receive messages from 14 platforms (Telegram, Slack, Discord, Email, WhatsApp, Feishu, DingTalk, QQ, Matrix, WeChat, etc.) and publish `InboundMessage` to an async queue.

2. **Bus** (`nanobot/bus/`) provides async queue decoupling between channels and the agent.

3. **Agent Loop** (`nanobot/agent/loop.py`) is the core engine — it builds context from session history + memory + skills, calls the LLM, executes tool calls in a loop (max 40 iterations), and publishes responses back.

4. **Context** (`nanobot/agent/context.py`) assembles the system prompt from bootstrap files in `nanobot/templates/` (AGENTS.md, SOUL.md, USER.md, TOOLS.md, MEMORY.md, HEARTBEAT.md).

5. **Memory** (`nanobot/agent/memory.py`) uses dual-layer storage: `MEMORY.md` (long-term facts) and `HISTORY.md` (timestamped event log), both in `workspace/memory/`.

6. **Tools** (`nanobot/agent/tools/`) register via `ToolRegistry`. Key tools: filesystem (128KB limit), shell (with blocked dangerous patterns), web (Brave Search + HTML fetch, 50KB limit), message, spawn (sub-agents), cron, MCP (30s timeout). Tool results are truncated at 16KB.

7. **Providers** (`nanobot/providers/`) offer a unified LLM interface via `litellm`. Provider selection is by model name prefix. Config is stored in `~/.nanobot/config.json`.

8. **Sessions** (`nanobot/session/manager.py`) use append-only JSONL files in `workspace/sessions/{channel}_{chat_id}.jsonl` for prompt caching efficiency.

9. **Gateway** (`nanobot/gateway/`) is a FastAPI server (port 18790) with SQLModel persistence, used when running multi-channel in server mode.

10. **Skills** (`nanobot/skills/`) are workspace-loaded prompt files. Only summaries (YAML frontmatter) load into context by default; full content loads on-demand to avoid context bloat.

## Key Design Decisions

- **Config schema** (`nanobot/config/schema.py`) uses Pydantic with camelCase JSON ↔ snake_case Python conversion.
- **Channel allow-list**: channels default to denying all senders; `allowFrom` must be configured.
- **Safety boundaries**: shell tool blocks `rm -rf`, `mkfs`, fork bombs; filesystem enforces workspace isolation and path traversal protection.
- **pytest-asyncio** is used for async tests; `asyncio_mode = "auto"` is set in `pyproject.toml`.
- **WhatsApp bridge**: TypeScript/Node.js service in `nanobot/bridge/` communicating over WebSocket to Python on localhost:3001.
