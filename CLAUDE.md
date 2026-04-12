# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Summary

pyccode is a single-file AI agent CLI (`pyccode.py`) that uses the Anthropic Messages API with multi-tool support (bash, read, write, edit). It supports an interactive REPL mode and single-prompt mode.

## Commands

```bash
# Install dependencies
uv sync

# Run interactively (REPL with `>> ` prompt, type `q`/`quit`/`exit` to stop)
python pyccode.py

# Run a single task
python pyccode.py "your task here"
```

No tests or linter are configured.

## Architecture

Everything lives in `pyccode.py`. Key components:

- **`SYSTEM`** — System prompt defining agent behavior rules (tool preference, subagent delegation)
- **`TOOLS`** — Anthropic tool-use schemas for 4 tools: `bash` (shell commands), `read` (file reading with line numbers), `write` (file creation/overwrite), `edit` (find-and-replace text editing)
- **`handle_bash`**, **`handle_read`**, **`handle_write`**, **`handle_edit`** — Tool handler functions that execute the requested operations
- **`chat(prompt, history)`** — Core agentic loop: sends messages to the API, dispatches tool calls to the appropriate handler, feeds results back iteratively until the model returns a final text response. Manages conversation history with tool_use/tool_result blocks.
- **`main()`** — CLI entry point. Dispatches to single-prompt or interactive REPL mode.
- **Subagent pattern** — The agent can spawn itself (`python pyccode.py "<task>"`) as a bash command to delegate complex subtasks with isolated context.

## Environment Configuration

Requires a `.env` file with:
- `ANTHROPIC_BASE_URL` — API endpoint (supports non-Anthropic providers with Anthropic-compatible APIs)
- `ANTHROPIC_API_KEY` — API key
- `MODEL_NAME` — Model to use (defaults to `claude-sonnet-4-5-20250929`)
- `ANTHROPIC_TIMEOUT` — Request timeout in seconds (defaults to `600`)

## Key Implementation Details

- Bash commands run via `subprocess.run` with `shell=True`, 300s timeout, output truncated to 50k chars
- Read tool returns file contents with line numbers, supports offset/limit for partial reads
- Write tool creates parent directories automatically, overwrites existing files
- Edit tool does exact string matching (including whitespace), fails if old_string is not unique
- Conversation history is accumulated in-memory as a list of message dicts
- The entry point is registered as `pyccode = "pyccode:main"` in `pyproject.toml`
- Python >=3.12 required