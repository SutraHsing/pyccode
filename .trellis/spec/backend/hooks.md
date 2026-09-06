# Hooks

> Extensibility framework: external subprocess scripts fire on specific events.

---

## Why Hooks?

Hooks let users observe (and, in future tasks, transform or veto) what
the agent does **without editing pyccode source**. Without hooks, these
five real features are awkward or impossible:

1. **Audit log** — "what did the agent run this session?" Needs to see
   every tool call.
2. **Secret scanning** — scan tool outputs for `AKIA...`, `ghp_...`,
   `xoxb-...`. Warn (cannot replace in MVP — read-only).
3. **Auto-format on write** — when agent writes a `.py` file, auto-run
   `ruff format`. For `.json`, validate with `jq .`.
4. **Custom validation** — user-defined business rules ("agent must
   not commit on main", "must run tests after edit").
5. **Cost / size tracking** — per-tool result size, per-session totals.

All five need: "after a tool runs, hand its data to an external script."
That's PostToolUse.

---

## Model

**Three tiers** (today: allow + observer-only; future: transformer + veto):

1. **Allow** — tool runs, no hook fires (no hooks configured).
2. **Observer hook (MVP)** — `PostToolUse` fires after every tool call.
   Hook subprocess receives JSON payload on stdin. stdout/exit code are
   captured but **ignored** by pyccode (chat loop continues regardless).
3. **Transformer / veto (future)** — hook can modify `tool_response`
   or block the tool. Reserved for later tasks.

---

## Internal vs External Hooks

Two dispatch lanes, run in order (internal first):

| | Internal hooks | External hooks |
|---|---|---|
| Registration | `register_internal_hook(event, fn)` in code | `~/.pyccode/settings.json` |
| Execution | In-process Python call | Subprocess (stdin JSON / exit code) |
| Always on | Yes | Per `enabled` flag |
| Who writes them | pyccode first-party features | Users |

**Why an internal-only lane exists**: Claude Code deliberately exposes only
*semantic* events (user submitted / tool ran / turn ended) as hook types —
mechanical mutation events would freeze internal plumbing into a public
contract. pyccode mirrors this: `MessageAppend` (fires on every
`history_append`) is internal-only — first-party hooks (the transcript
writer) register on it, but settings.json entries for it are **skipped with
a stderr warning** (`EXTERNAL_EVENTS` allowlist in `hooks/settings.py`).

Current internal hooks:

- `_transcript_message_append_hook` (in `pyccode/context/transcript.py`) —
  writes one JSONL transcript entry per message append, with `gitBranch`
  and assistant-entry `message.usage`.

Internal hook failures print `[Internal hook '<fn>' failed: ...]` to stderr
and never break the chat loop.

---

## MVP Scope: PostToolUse, Read-Only Observer

### Configuration

`~/.pyccode/settings.json` (single user-global file; project-local
override is a future task):

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "command": "python3 examples/hooks/audit.py",
        "timeout_ms": 5000,
        "enabled": true
      }
    ]
  }
}
```

Only `command` is required. Defaults: `timeout_ms=5000`, `enabled=true`.

### Subprocess Contract

| Channel | Content |
|---|---|
| **stdin** | Single JSON object (UTF-8), the payload. No trailing newline required. |
| **stdout** | Captured. MVP does not parse it. (Future transformer hooks will parse JSON.) |
| **stderr** | Captured. On non-zero exit, pyccode prints it to its own stderr. |
| **exit code** | `0` = success. Non-zero = failure (pyccode prints `[Hook '<cmd>' failed: exit N]` to stderr, continues). |

### Firing Point

In `chat()` main loop and `handle_subagent()` sub-agent loop, **after**
the handler returns and **before** `maybePersistLargeToolResult` (Layer 1).

Rationale: hooks see raw handler output (full size), useful for audit
and secret scan. Layer 1+ still run after, doing their normal job.

Fires **once per `tool_result`** — multiple tool calls in one assistant
turn produce multiple PostToolUse events.

### Payload Schema (12 fields)

| Field | Type | Source |
|---|---|---|
| `hook_event_name` | `'PostToolUse'` | literal, matches Claude Code |
| `session_id` | str | `SESSION_ID` (uuid4 hex) |
| `transcript_path` | str | `str(TRANSCRIPT_PATH)` |
| `cwd` | str | `str(WORKDIR)` |
| `permission_mode` | `'default'` | `PermissionMode.DEFAULT.value` (MVP always default) |
| `timestamp` | str | `datetime.now(timezone.utc).isoformat()` (pyccode-specific; Claude Code omits) |
| `agent_id` | `'main' \| 'subagent'` | passed by caller (pyccode-specific simplification of Claude Code's `agent_id`+`agent_type`) |
| `tool_name` | str | from `tool_use.name` |
| `tool_use_id` | str | from `tool_use.id` |
| `tool_input` | dict | from `tool_use.input` |
| `tool_response` | str | handler return value (string, not structured — pyccode-specific divergence from Claude Code's `{stdout, stderr, exitCode}`) |
| `tool_error` | bool | `tool_response.startswith("Error:")` (pyccode-specific; gives hooks a quick success/failure signal without string parsing) |

### Three Intentional Divergences from Claude Code

1. **`agent_id` is a label, not UUID.** Claude Code uses UUID + type.
   pyccode has no per-subagent UUID and no typed subagent — one field
   suffices.
2. **`tool_response` is a string.** Claude Code's Bash returns
   `{stdout, stderr, exitCode}`. pyccode's handler contract is
   combined-string. Changing this is a separate refactor task.
3. **`tool_error` is pyccode-specific.** Because response is
   unstructured, hooks can't tell OK from Error without string
   parsing. pyccode computes it via the `"Error: "` prefix convention
   (matches existing handler error returns).

---

## Failure Isolation

`run_hooks` never raises. All failure paths produce stderr output and
return:

| Scenario | pyccode behavior |
|---|---|
| `~/.pyccode/settings.json` missing | empty settings, no hooks fire |
| `settings.json` malformed JSON | stderr `[Settings load failed: ...]`, treat as empty |
| Hook entry missing `command` | skip + stderr warning |
| `timeout_ms` not int | skip + stderr warning |
| Subprocess non-zero exit | stderr `[Hook '<cmd>' failed: exit N]`, continue |
| Subprocess timeout | killed, stderr `[Hook '<cmd>' timed out after Xms]`, continue |
| Subprocess can't spawn | captured as non-zero exit, same stderr format |

Chat loop is never broken by hook failures.

---

## Adding a New Hook Type (Future Tasks)

To add a new event type (e.g. `PreToolUse`):

1. Add a new value to `HookType` enum in `pyccode/hooks/engine.py`.
2. Add a payload builder (mirrors `build_post_tool_use_payload`).
3. Wire `run_hooks(NewType, payload)` at the firing point in `chat()`
   or `handle_subagent()`.
4. Update this spec with the new event's contract.
5. If the new type needs output parsing (transformer / veto), add
   stdout JSON parsing to `run_hook` and decision handling to the
   integration site.

Future hook types already motivated:

- **PreToolUse** — custom permission rules; veto support (TODO: Task 3
  of the hooks series; needs stdout output contract).
- **UserPromptSubmit** — prompt enrichment before sending to LLM;
  inject git status, recent commits, etc.
- **Stop** (deferred; design recorded) — fires at `chat()` end_turn
  before return. High-value scenarios, by practicality:
  1. Completion notification — osascript / terminal bell / ntfy push
     when a long task finishes.
  2. Turn report — token totals, tool-call count, `git diff --stat`.
  3. Teardown — kill agent-spawned processes, remove scratch files.
  4. Guard loop (Claude Code's signature Stop use) — hook runs tests;
     on failure returns `decision: "block"` forcing the agent to keep
     working until green. Requires veto semantics (Task 3+).
  Slim payload sketch: common fields + `stop_reason` + `user_prompt` +
  `usage_totals` + `last_message`.
- **SubagentStop** — subagent transcript coverage (subagent `messages.append`
  bypasses `history_append` today, so subagent turns stay un-transcribed).

---

## See Also

- [chat-loop.md](./chat-loop.md) — PostToolUse firing point in the loop diagram
- [error-handling.md](./error-handling.md) — hook failure isolation patterns
- [logging-guidelines.md](./logging-guidelines.md) — `[Hook ... failed]` and `[Settings load failed]` prefixes
- `examples/hooks/audit.py` — working example hook
