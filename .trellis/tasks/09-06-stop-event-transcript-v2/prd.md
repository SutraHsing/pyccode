# Transcript v2 via internal MessageAppend hook

## Goal

Introduce an **internal hook** mechanism (in-process, code-registered, always-on),
add an internal-only **MessageAppend** event fired on every conversation
mutation, and refactor the transcript writer to be an internal hook on that
event — preserving v1's incremental timing while routing through the hook
dispatch. Enrich entries with Claude Code-parity fields: `gitBranch` and
`message.usage`.

## Background

Design discussion (see hooks.md spec for the full reasoning) settled three
things:

1. **Claude Code deliberately has no message-append hook.** Its transcript is
   first-party infrastructure observing the messages array directly; hooks are
   *semantic* events (user submitted / tool ran / turn ended) kept as a stable
   third-party contract. Mechanical mutation events are never exposed
   externally.
2. **Our resolution**: a `MessageAppend` event that is **internal-only** —
   usable by in-process first-party hooks, never dispatchable to external
   subprocess hooks. External contract stays aligned with Claude Code's event
   list; internal plumbing gets the unification benefits.
3. **Incremental beats batch here**: firing per message append (v1 timing)
   keeps crash-loss at "one message" instead of "one turn", and needs no
   dedup. The earlier batch-at-Stop design was dropped.

`Stop` event: **deferred** — recorded below with its use cases for a future
task; not in scope.

## Requirements

### Functional

**Internal hook mechanism** (`pyccode/hooks/engine.py`):

- `register_internal_hook(event, fn)` — code-registered, always-on registry.
- `run_hooks(event, payload)` dispatches internal hooks first (in-process),
  then external (subprocess from settings.json). Internal hook exceptions are
  caught + logged to stderr; never break the chat loop.

**Internal-only gating** (`pyccode/hooks/settings.py`):

- `EXTERNAL_EVENTS = frozenset({"PostToolUse"})` — settings.json entries for
  any other event name (notably `MessageAppend`) are skipped with a stderr
  warning. Keeps the external contract aligned with Claude Code's hook list.

**MessageAppend event**:

- `HookType.MESSAGE_APPEND = "MessageAppend"`.
- Fired inside `history_append` on every call — user prompts, assistant
  turns, tool-result messages, max-tokens continuations, round-counter
  reminders, compact boundary/summary.
- Payload: `hook_event_name`, `session_id`, `cwd`, `timestamp`, `role`,
  `content`, `usage` (dict or None).

**Transcript internal hook** (in `pyccode/context/transcript.py`):

- Registered on `MessageAppend` at module import (single registration site at
  the bottom of the module).
- Writes exactly one transcript entry per fire — v1 incremental semantics,
  same uuid/parentUuid chain.
- `history_append` drops its inline `appendTranscript` call; signature gains
  optional `usage` param, passed through to the payload.

**Field enrichment**:

- `appendTranscript(role, content, usage=None)`: assistant entries embed
  `message.usage`; every entry gains top-level `gitBranch`.
- `gitBranch`: parse `.git/HEAD` (no subprocess); branch name, or None when
  not a repo / detached / worktree.
- `chat()` passes `response.usage` (as a small dict) to `history_append` for
  assistant turns. No other call sites pass usage.

**Compact path**: unchanged code — `maybeAutoCompact` already calls
`history_append`, which now fires MessageAppend automatically. No special
handling (this is simpler than the dropped batch design).

### Non-functional

- Transcript write failure prints `[Transcript write failed: ...]` to stderr;
  never breaks the chat loop (existing behavior preserved).
- `.git/HEAD` read per append is one small file read; acceptable at
  conversation frequency.
- No new external dependencies.

## Acceptance Criteria

- [ ] `register_internal_hook` + internal-first dispatch works; internal hook
      failure prints stderr and does not raise.
- [ ] `history_append` fires MessageAppend; the registered transcript hook
      writes one entry per call — behavior identical to v1 except new fields.
- [ ] Pure-text turn produces user + assistant entries; assistant entry has
      `message.usage` (from real API response).
- [ ] Tool turn produces user / assistant / tool-result entries in order with
      unbroken uuid chain.
- [ ] Every entry carries `gitBranch` (branch name in this repo).
- [ ] REPL: second `chat()` call continues the same uuid chain.
- [ ] Auto-compact boundary + summary entries land in transcript (via the
      unchanged `history_append` path).
- [ ] External PostToolUse hooks still fire (regression).
- [ ] settings.json configuring `MessageAppend` as external hook → skipped
      with stderr warning; no subprocess spawned.
- [ ] Transcript failure (unwritable path) → stderr notice, chat unaffected.

## Out of Scope (Future Tasks)

- **Stop event (deferred, with recorded use cases)**: fires at `chat()`
  end_turn before return. High-value scenarios: (1) completion notification
  (osascript / terminal bell / ntfy); (2) turn report (token totals, tool
  count, `git diff --stat`); (3) teardown/cleanup of agent-spawned processes
  or scratch files; (4) guard-loop — block stop until tests pass (Claude
  Code's signature Stop use; requires veto semantics from Task 3). Slim
  payload sketch: common fields + `stop_reason` + `user_prompt` +
  `usage_totals` + `last_message`.
- Subagent transcript coverage (needs SubagentStop or MessageAppend wiring in
  `handle_subagent` — deliberate v1 behavior unchanged).
- PostToolUse payload enrichment (user_prompt / assistant_message / usage).
- Transcript resume/read path.
