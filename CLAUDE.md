# Agent Instructions

This file provides guidance to AI coding agents when working with code in this repository.

## Project Summary

pyccode is a single-file AI agent CLI (`pyccode.py`) that uses the Anthropic Messages API with multi-tool support (bash, read, write, edit, TodoWrite, skill, run_subagent). It supports an interactive REPL mode and single-prompt mode.

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

- **`_BASE_SYSTEM`** / **`SYSTEM`** — Two-tier system prompt. `_BASE_SYSTEM` has core rules; `SYSTEM` extends it with subagent delegation instructions. Subagents get `_BASE_SYSTEM` only (cannot recurse).
- **`TOOLS`** — Anthropic tool-use schemas for 6 base tools: `bash`, `read`, `write`, `edit`, `TodoWrite`, `skill`
- **`SUBAGENT_TOOL`** — Separate schema for `run_subagent`, only added to the main agent's tool list (`TOOLS + [SUBAGENT_TOOL]`), not available to subagents
- **`TOOL_HANDLERS`** — Dispatch dict mapping tool names to handler functions
- **`load_skills()`** / **`SKILLS`** — Loads `skills/*/SKILL.md` files at startup. Each skill requires frontmatter; `name` defaults to the directory name and `description` defaults to an empty string.
- **`Task`** / **`TaskStore`** — Dataclasses for in-memory task tracking with a `write()` method that replaces the entire list
- **`handle_bash`**, **`handle_read`**, **`handle_write`**, **`handle_edit`**, **`handle_todo`**, **`handle_skill`**, **`handle_subagent`** — Tool handler functions
- **`handle_skill`** — Returns a skill's full markdown instructions and absolute skill directory path, so the agent can load domain-specific guidance and nearby reference files on demand.
- **`handle_subagent`** — In-process sub-agent: creates its own conversation loop with isolated `TaskStore`, uses `_BASE_SYSTEM` and `TOOLS` (including `skill`, but no `SUBAGENT_TOOL` to prevent recursion). Swaps the global `_task_store` and restores it in a `finally` block.
- **`chat(prompt, history)`** — Core agentic loop: sends messages to the API, dispatches tool calls via `TOOL_HANDLERS`, feeds results back iteratively until `end_turn`. Handles `max_tokens` truncation by injecting "Continue where you left off." Manages conversation history with tool_use/tool_result blocks. On the first message, injects available skill names and descriptions from `SKILLS`. Includes a round-counter that injects a reminder to use `TodoWrite` after 5 consecutive tool-use rounds without task tracking.
- **`main()`** — CLI entry point. Dispatches to single-prompt or interactive REPL mode.

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
- Edit tool does exact string matching (including whitespace), replaces **all** occurrences of `old_string`
- TodoWrite replaces the entire task list each call. Tasks have `content` (imperative), `activeForm` (present continuous), and `status` (pending/in_progress/completed)
- Skills live in `skills/<skill-name>/SKILL.md`. Files without YAML frontmatter are ignored; the `skill` tool returns the body without frontmatter plus the skill directory path.
- Subagent runs in-process (not a shell spawn), gets isolated context — only the prompt passed to it, no shared conversation history
- After 5 tool-use rounds without using `TodoWrite`, a reminder is injected into the conversation history
- Conversation history is accumulated in-memory as a list of message dicts
- Tool outputs are truncated to 50k chars before being sent back to the API
- The entry point is registered as `pyccode = "pyccode:main"` in `pyproject.toml`
- Python >=3.12 required

<!-- TRELLIS:START -->
# Trellis Instructions

These instructions are for AI assistants working in this project.

This project is managed by Trellis. The working knowledge you need lives under `.trellis/`:

- `.trellis/workflow.md` — development phases, when to create tasks, skill routing
- `.trellis/spec/` — package- and layer-scoped coding guidelines (read before writing code in a given layer)
- `.trellis/workspace/` — per-developer journals and session traces
- `.trellis/tasks/` — active and archived tasks (PRDs, research, jsonl context)

If a Trellis command is available on your platform (e.g. `/trellis:finish-work`, `/trellis:continue`), prefer it over manual steps. Not every platform exposes every command.

If you're using Codex or another agent-capable tool, additional project-scoped helpers may live in:
- `.agents/skills/` — reusable Trellis skills
- `.codex/agents/` — optional custom subagents

Managed by Trellis. Edits outside this block are preserved; edits inside may be overwritten by a future `trellis update`.

<!-- TRELLIS:END -->
