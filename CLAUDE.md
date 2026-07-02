# Agent Instructions

This file provides guidance to AI coding agents when working with code in this repository.

## Project Summary

pyccode is an AI agent CLI built on the Anthropic Messages API with multi-tool support (bash, read, write, edit, TodoWrite, skill, run_subagent). The root `pyccode.py` is a 5-line thin wrapper; all logic lives in the `pyccode/` package. Supports interactive REPL mode and single-prompt mode.

## Commands

```bash
# Install dependencies
uv sync

# Run interactively (REPL with `>> ` prompt, type `q`/`quit`/`exit` to stop)
python pyccode.py
# or
python -m pyccode

# Run a single task
python pyccode.py "your task here"
```

No tests or linter are configured.

## Architecture

Code lives in the `pyccode/` package. Module map:

- **`pyccode.config`** — Constants (`WORKDIR`, `SESSION_ID`, all thresholds, `TRANSCRIPT_*`, `AUTOCOMPACT_*`, `COMPACTABLE_TOOLS`, etc.), system prompts (`BASE_SYSTEM`, `SYSTEM`), `load_dotenv`, shared `client = Anthropic(...)`. Leaf module.
- **`pyccode.tools`** — Package: one module per leaf tool (`bash`, `file` for read/write/edit, `skill`, `todo` for Task/TaskStore/handle_todo). `__init__.py` assembles `TOOLS` (6 leaf schemas, no subagent), `TOOL_HANDLERS` (6 leaf dispatch entries), `SUBAGENT_TOOL` schema, and re-exports `SKILLS`, `_task_store`.
- **`pyccode.context.transcript`** — `appendTranscript`, `history_append`, `_transcript_last_uuid` chain state.
- **`pyccode.context.layers`** — Four-layer context management: `_persist_tool_result` (private disk-write + preview builder), `maybePersistLargeToolResult` (per-result, >50K), `enforceToolResultBudget` (per-message, >200K total), `microcompactMessages` (per-turn, >10 uncleared compactable), `maybeAutoCompact` (per-turn LLM summary when previous input_tokens > 150K). Plus private helpers `_callCompactLLM`, `_buildCompactSummaryMessage`.
- **`pyccode.chat`** — `chat()` main agent loop + `handle_subagent()` sub-agent loop (both chat-loop code). Builds the run_subagent-aware `TOOL_HANDLERS` locally: `{**leaf_handlers, "run_subagent": handle_subagent}`. Sub-agent invocations pass `tools=TOOLS` (no `SUBAGENT_TOOL`), so the model never asks for `run_subagent` even though the dispatch entry exists.
- **`pyccode.main`** — CLI entry point. Dispatches to single-prompt mode (`pyccode "<task>"`) or interactive REPL (`pyccode`).
- **`pyccode/__init__.py`** — Re-exports `main` so the `pyccode = "pyccode:main"` entry point in `pyproject.toml` works.
- **`pyccode/__main__.py`** — Enables `python -m pyccode` execution.
- **`pyccode.py`** (repo root) — 5-line thin wrapper: `from pyccode.main import main`.

### Key components by name

- **`BASE_SYSTEM`** / **`SYSTEM`** — Two-tier system prompt (in `config`). `BASE_SYSTEM` has core rules; `SYSTEM` extends it with subagent delegation instructions. Subagents get `BASE_SYSTEM` only (cannot recurse).
- **`TOOLS`** — Anthropic tool-use schemas for 6 base tools: `bash`, `read`, `write`, `edit`, `TodoWrite`, `skill`
- **`SUBAGENT_TOOL`** — Separate schema for `run_subagent`, only added to the main agent's tool list (`TOOLS + [SUBAGENT_TOOL]`), not available to subagents
- **`TOOL_HANDLERS`** — Dispatch dict mapping tool names to handler functions
- **`load_skills()`** / **`SKILLS`** — Loads `skills/*/SKILL.md` files at startup. Each skill requires frontmatter; `name` defaults to the directory name and `description` defaults to an empty string.
- **`Task`** / **`TaskStore`** — Dataclasses for in-memory task tracking with a `write()` method that replaces the entire list
- **`handle_bash`**, **`handle_read`**, **`handle_write`**, **`handle_edit`**, **`handle_todo`**, **`handle_skill`**, **`handle_subagent`** — Tool handler functions
- **`handle_skill`** — Returns a skill's full markdown instructions and absolute skill directory path, so the agent can load domain-specific guidance and nearby reference files on demand.
- **`handle_subagent`** — In-process sub-agent: creates its own conversation loop with isolated `TaskStore`, uses `_BASE_SYSTEM` and `TOOLS` (including `skill`, but no `SUBAGENT_TOOL` to prevent recursion). Swaps the global `_task_store` and restores it in a `finally` block.
- **`maybePersistLargeToolResult`** — Layer 1 of context management. Called from both `chat()` and `handle_subagent()` per tool result. Outputs over `LARGE_TOOL_RESULT_THRESHOLD` (50K chars) are written in full to `~/.pyccode/projects/<sanitized-cwd>/<sessionId>/tool-results/<id>.{txt|json}` (extension auto-sniffed via `json.loads`) and replaced in the conversation with a head-only summary (~2KB, `SUMMARY_HEAD_CHARS = 2000` slice + small metadata). Under-threshold outputs pass through unchanged; filesystem failure falls back to legacy 50K truncation with an error note.
- **`enforceToolResultBudget`** — Layer 2. Called per user message (after Layer 1 has run on each result). When the sum of `len(content)` across all `tool_result` blocks in the message exceeds `TOOL_RESULT_MESSAGE_BUDGET` (200K chars), persists the largest results first via the shared `_persist_tool_result` helper until under budget. Results already `<= 2 * SUMMARY_HEAD_CHARS` are skipped (would not shrink).
- **`microcompactMessages`** — Layer 3. Called per turn before each API call. When the count of **uncleared compactable** `tool_result` blocks in the whole history exceeds `MICROCOMPACT_MAX_TOOL_RESULTS` (10), replaces the oldest ones' content with `OLD_TOOL_RESULT_PLACEHOLDER`, keeping the most recent `MICROCOMPACT_KEEP_RECENT` (5) intact. Compactable tools (`COMPACTABLE_TOOLS`): `{bash, read, write, edit, TodoWrite, skill}` — `run_subagent` excluded because sub-agent outputs are one-shot. Counts only uncleared blocks so compaction batches every `MAX - KEEP_RECENT` turns instead of every turn. Whole body wrapped in try/except returning history unchanged on any failure.
- **`maybeAutoCompact`** — Layer 4. Called per turn before each API call (after Layer 3). Reactive trigger via `last_input_tokens` (local to `chat()`, set from `response.usage.input_tokens` after each API response — real data, no estimation). When `last_input_tokens > AUTOCOMPACT_THRESHOLD` (150K = 200K window - 20K output reserve - 30K buffer), calls the model with a 9-section summary prompt and replaces history in place with `[boundary_msg, summary_msg, *last_4_messages]`. Boundary (`[compact_boundary]`) and summary go through `history_append` so they land in transcript; recent 4 are re-inserted as references (not re-appended, transcript idempotency). `_callCompactLLM` lets exceptions propagate; `maybeAutoCompact`'s try/except prints `[Auto-compact failed: ...]` to stderr and returns False so chat loop is unaffected. `handle_subagent` does NOT call this (subagent tasks are short by design).
- **`appendTranscript`** — Write-side transcript logger. Appends one JSON object per line to `~/.pyccode/projects/<sanitized-cwd>/<SESSION_ID>.jsonl` (sanitized cwd collapses non-`[A-Za-z0-9._-]` to `-`). Schema: `type` / `uuid` / `parentUuid` (chain) / `timestamp` / `sessionId` / `cwd` / `version` / `message`. Open-write-close per entry; `ensure_ascii=False` keeps non-ASCII verbatim. Whole body wrapped in try/except; failures print `[Transcript write failed: ...]` to **stderr** and never break the chat loop. Write-only in MVP — no resume logic.
- **`history_append`** — Helper called by all `chat()` history mutations: does `history.append(...)` + `appendTranscript(...)` in one step. The five migrated sites: initial user prompt, assistant turn, tool-result user message, max-tokens continuation, TodoWrite round-counter reminder. `handle_subagent`'s `messages.append` is intentionally NOT routed here, so subagent turns stay un-transcribed in MVP.
- **`_persist_tool_result`** — Private helper (inside `context.layers`) shared by Layer 1 and Layer 2: writes `output` to disk, returns the head-only summary. Never raises.
- **`SESSION_ID`** — Process-level `uuid4().hex`, shared by the main agent and all subagents, scoping the persisted-results directory and transcript filename.
- **`chat(prompt, history)`** — Core agentic loop: sends messages to the API, dispatches tool calls via `TOOL_HANDLERS`, feeds results back iteratively until `end_turn`. Handles `max_tokens` truncation by injecting "Continue where you left off." Manages conversation history with tool_use/tool_result blocks. On the first message, injects available skill names and descriptions from `SKILLS`. Includes a round-counter that injects a reminder to use `TodoWrite` after 5 consecutive tool-use rounds without task tracking.
- **`main()`** — CLI entry point. Dispatches to single-prompt or interactive REPL mode.

## Environment Configuration

Requires a `.env` file with:
- `ANTHROPIC_BASE_URL` — API endpoint (supports non-Anthropic providers with Anthropic-compatible APIs)
- `ANTHROPIC_API_KEY` — API key
- `MODEL_NAME` — Model to use (defaults to `claude-sonnet-4-5-20250929`)
- `ANTHROPIC_TIMEOUT` — Request timeout in seconds (defaults to `600`)

## Key Implementation Details

- Bash commands run via `subprocess.run` with `shell=True`, 300s timeout
- Read tool returns file contents with line numbers, supports offset/limit for partial reads
- Write tool creates parent directories automatically, overwrites existing files
- Edit tool does exact string matching (including whitespace), replaces **all** occurrences of `old_string`
- TodoWrite replaces the entire task list each call. Tasks have `content` (imperative), `activeForm` (present continuous), and `status` (pending/in_progress/completed)
- Skills live in `skills/<skill-name>/SKILL.md`. Files without YAML frontmatter are ignored; the `skill` tool returns the body without frontmatter plus the skill directory path.
- Subagent runs in-process (not a shell spawn), gets isolated context — only the prompt passed to it, no shared conversation history
- After 5 tool-use rounds without using `TodoWrite`, a reminder is injected into the conversation history
- Conversation history is accumulated in-memory as a list of message dicts
- Tool outputs over 50K chars are persisted to `~/.pyccode/projects/<sanitized-cwd>/<sessionId>/tool-results/<id>.{txt|json}` (never inside `WORKDIR`) and replaced in the conversation with a ~2KB head-only summary pointing at the file; under-50K outputs pass through unchanged
- Tool result context management is four-layered: (1) per-result, >50K → persist + preview; (2) per-message, >200K total → persist largest-first until under budget; (3) per-turn, >10 uncleared compactable results in whole history → replace oldest with `[Old tool result content cleared]`, keeping recent 5; (4) per-turn, previous response's input_tokens > 150K → LLM-summarize whole history and replace with `[boundary, summary, *last_4]`
- Transcript logging: every main-agent `history.append` in `chat()` is mirrored (via `history_append`) to `~/.pyccode/projects/<sanitized-cwd>/<sessionId>.jsonl` as one JSON object per line with a `parentUuid` chain. Write-only in MVP — no resume. Subagent turns are not transcribed. `microcompactMessages` mutates in-memory history only; old tool_result entries keep their full content in the transcript (future resume work will need `content-replacement` entries to preserve the placeholder effect across sessions). Compact boundary (`[compact_boundary]`) and summary entries also flow through `history_append` and are append-only in transcript.
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
