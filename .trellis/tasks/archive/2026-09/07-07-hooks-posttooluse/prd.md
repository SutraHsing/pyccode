# Hook framework: PostToolUse subprocess observer

## Goal

Add a Hook framework to pyccode that fires external subprocess scripts when
specific events occur. MVP scope: **PostToolUse** event, **read-only
observer** semantics (no modification of tool_result, no veto), configured
via `~/.pyccode/settings.json`.

## Background

pyccode today has no extension points beyond editing source. Several real
features are awkward or impossible without an event system:

1. **Audit log** — "what did the agent run this session?" needs hooks into
   every tool call.
2. **Secret masking** — scan tool outputs for `AKIA...`, `ghp_...`,
   `xoxb-...` patterns; warn (cannot replace in MVP — read-only).
3. **Auto-format on write** — when agent uses `write` to create a `.py`
   file, auto-run `ruff format`; for `.json`, validate with `jq .`.
4. **Custom validation** — user-defined business rules ("agent must not
   commit on main", "agent must run tests after edit").
5. **Cost / size tracking** — per-tool result size, per-session totals.

All five need the same primitive: "after a tool runs, hand its data to
an external script". That's PostToolUse.

## Requirements

### Functional

- New `pyccode/hooks/` package with:
  - `HookType` enum (single value: `POST_TOOL_USE` for MVP)
  - `HookConfig` dataclass (command, timeout_ms, enabled)
  - `run_hook(config, payload) -> HookOutcome` — single hook executor
  - `run_hooks(event, payload) -> None` — dispatches to all configured
    hooks for that event type
  - `load_settings() -> SettingsSchema` — reads `~/.pyccode/settings.json`
    once at startup, caches
- PostToolUse fires **once per tool_result**, after the handler returns
  and **before Layer 1** (`maybePersistLargeToolResult`). Rationale: hooks
  see the raw output, can scan full content for secrets / log full size.
  Layer 1+ still run after, doing their normal job.
- Fires for **both main agent and subagent** tool calls. Payload includes
  `agent_id` field to distinguish.
- Configuration via `~/.pyccode/settings.json` (single user-global file
  for MVP; project-local override is a future task). Schema:

  ```json
  {
    "hooks": {
      "PostToolUse": [
        {"command": "python3 ~/.pyccode/hooks/audit.py", "timeout_ms": 5000}
      ]
    }
  }
  ```

- Hook subprocess contract:
  - **stdin**: JSON payload (UTF-8, single object, no trailing newline
    required but tolerated)
  - **stdout**: parsed as JSON if non-empty (for future use; MVP ignores
    content), unstructured text otherwise
  - **stderr**: captured; on non-zero exit, printed to pyccode's stderr
    with `[Hook '<name>' failed: exit N]` prefix
  - **exit code**: `0` = success, non-zero = failure (pyccode continues
    regardless; failure is logged, never breaks chat loop)

### Payload schema (10 fields, stdin JSON)

| Field | Type | Source | Notes |
|---|---|---|---|
| `hook_event_name` | `'PostToolUse'` | literal | Matches Claude Code |
| `session_id` | str | `SESSION_ID` (uuid4 hex) | |
| `transcript_path` | str | `str(TRANSCRIPT_PATH)` | Already implemented in pyccode; audit hooks can read full session JSONL |
| `cwd` | str | `str(WORKDIR)` | |
| `permission_mode` | `'default'` | `PermissionMode.DEFAULT.value` | MVP always "default"; future modes will populate this |
| `timestamp` | str | `datetime.now(timezone.utc).isoformat()` | ISO 8601 UTC; pyccode-specific addition (Claude Code omits) |
| `agent_id` | `'main' \| 'subagent'` | passed by chat / handle_subagent | Simplified from Claude Code's `agent_id` (UUID) + `agent_type` |
| `tool_name` | str | `content.name` from tool_use | e.g. `"bash"`, `"read"`, `"write"` |
| `tool_use_id` | str | `content.id` from tool_use | Matches transcript's `tool_use_id` |
| `tool_input` | dict | `content.input` from tool_use | Original tool args |
| `tool_response` | str | handler return value | pyccode-specific: string, not structured (Claude Code uses `{stdout, stderr, exitCode}` for Bash) |
| `tool_error` | bool | `tool_response.startswith("Error:")` | pyccode-specific: derived since response is unstructured string |

**Three intentional divergences from Claude Code** (documented in spec):

1. `agent_id` is a label `"main"|"subagent"`, not a UUID. pyccode has no
   per-subagent UUID and no typed subagent (`agent_type` field omitted).
2. `tool_response` is a plain string. Claude Code's Bash returns
   structured `{stdout, stderr, exitCode}`; pyccode's handler contract
   returns combined `stdout+stderr` as string.
3. `tool_error` is pyccode-specific. Because response is unstructured,
   hooks can't tell success from failure without parsing the string.
   pyccode computes it via the `"Error: "` prefix convention (matches
   existing handler error returns).

### Non-functional

- Hook subprocess has 5-second default timeout (configurable per hook).
- Subprocess failures never crash the chat loop.
- `settings.json` parse failures print stderr warning and behave as if
  no hooks configured.
- No new external dependencies; uses stdlib `subprocess`, `json`.

## Acceptance Criteria

- [ ] `~/.pyccode/settings.json` with one PostToolUse hook fires once
      per `tool_result` in main agent chat loop.
- [ ] Same hook also fires for subagent tool calls (payload `agent_id`
      is `"subagent"`).
- [ ] Hook receives JSON on stdin matching the 12-field payload schema
      (10 listed + `tool_input`/`tool_response` as values).
- [ ] `tool_error` is `True` when handler returned `"Error: ..."`,
      `False` otherwise.
- [ ] Hook subprocess timing: fires **before** Layer 1 persistence
      (hook sees raw handler output, not the 2KB summary).
- [ ] Hook subprocess non-zero exit prints `[Hook '<command>' failed:
      exit N]` to stderr; chat loop continues.
- [ ] Hook subprocess exceeding `timeout_ms` is killed; same stderr
      notice; chat loop continues.
- [ ] Missing or malformed `settings.json` → no hooks fire, no crash.
- [ ] Empty `hooks` config or empty `PostToolUse` array → no hooks fire.
- [ ] A documented example hook script (audit logger writing to
      `~/.pyccode/audit.jsonl`) shipped in `examples/hooks/`.

## Out of Scope (Future Tasks)

- **Other hook types**: `PreToolUse` (custom permission + veto),
  `UserPromptSubmit` (prompt enrichment), `Stop` (session-end reporting).
- **Hook output contract**: stdout JSON parsing for `additionalContext`,
  `decision: "block"`, `continue: false`. MVP reads exit code only.
- **Modify tool_response**: hooks cannot replace tool output (needed for
  real secret masking, not just warning).
- **Async / parallel hook execution**: MVP runs hooks serially.
- **Project-local settings.json override**: MVP is user-global only.
- **Multiple PermissionMode values**: MVP always `"default"`.
- **Hook for non-tool events** (skill load, subagent spawn, etc.).
