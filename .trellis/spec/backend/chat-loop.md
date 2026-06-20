# Chat Loop Invariants

> `chat(prompt, history)` (pyccode.py:628) and `handle_subagent` (pyccode.py:460) share the same agentic shape. This spec lists the invariants both must preserve.

---

## Loop Shape

```
while True:
    response = client.messages.create(...)
    collect assistant_content into history
    if stop_reason == "end_turn":   return text
    if stop_reason == "max_tokens": inject "Continue where you left off."; continue
    execute tool calls
    wrap each result via maybePersistLargeToolResult
    append tool_result list as a single user message
```

`handle_subagent` uses the same shape with `_BASE_SYSTEM`, `TOOLS` (no `SUBAGENT_TOOL`), and an isolated `TaskStore`.

---

## History Accumulation

- History is a `list[dict]` of `{"role": ..., "content": ...}`.
- Tool calls produce two history entries: one assistant message (`tool_use` blocks), one user message (a list of `tool_result` blocks).
- Never append tool results one-by-one. Always batch all tool_results from one assistant turn into a single user message. The API requires this.

---

## Tool Result Size Cap

Two-layer model. Both layers share `_persist_tool_result` (the disk-write +
preview builder); the wrappers decide when to call it.

```
for each tool_use:
    content = maybePersistLargeToolResult(id, output)   # layer 1: per-result (>50K)
    results.append({tool_result, content})
results = enforceToolResultBudget(results)              # layer 2: per-message (>200K total)
history.append({role: user, content: results})
```

### Layer 1 — `maybePersistLargeToolResult` (per result)

Triggered per result when `len(output) > LARGE_TOOL_RESULT_THRESHOLD` (50K
chars). Writes the full output to disk, replaces with a ~2.2KB preview.
See pyccode.py:600.

### Layer 2 — `enforceToolResultBudget` (per message)

Triggered per message when the sum of `len(content)` across all
`tool_result` blocks exceeds `TOOL_RESULT_MESSAGE_BUDGET` (200K chars).
Sorts results by content size descending and persists largest-first via
`_persist_tool_result` until the total fits. See pyccode.py:626.

Skip heuristic: results with `len(content) <= 2 * SUMMARY_HEAD_CHARS`
(4KB) are left alone — re-persisting would not shrink them (they may
already be Layer-1 summaries, or genuinely small).

### Shared rules

- File layout: `WORKDIR / SESSION_ID / "tool-results" / <safe_id>.{txt|json}`.
- Extension sniffed via `json.loads` — `.json` if valid, otherwise `.txt`.
- `id` sanitized with `re.sub(r'[^A-Za-z0-9_-]', '_', tool_use_id)`.
- Preview format: head-only `SUMMARY_HEAD_CHARS` (2000) slice + small
  metadata (`[tool_result_persisted]`, original length, persisted path).
  Does not prescribe a downstream tool — the agent picks.
- On filesystem failure: `_persist_tool_result` returns legacy 50K
  truncation with `[persist failed: <error>]` appended. Never raises.
  Layer 2 continues to the next result on per-result failure.

### Forbidden

`output[:50000]` style hard truncation is forbidden anywhere except
inside `_persist_tool_result`'s error fallback. It silently drops the
tail with no recovery path.

Both `chat()` and `handle_subagent()` must run both layers. Adding a new
agentic loop means inheriting the same contract.

---

## Skill Metadata Injection

First user message of a fresh history gets prepended with:

```
<system-reminder>
Available skills:
- <name>: <description>
...
</system-reminder>
```

Applied in `chat()` (pyccode.py:644) and `handle_subagent` (pyccode.py:503). When adding a new injection point, mirror this exact wrapper.

---

## Round-Counter Reminder (main agent only)

After 5 consecutive tool-use rounds without a `TodoWrite` call, `chat()` injects a user message nudging the model to plan. Counter resets to 0 on any `TodoWrite` call. See pyccode.py:708.

`handle_subagent` does NOT have this counter — subagent tasks are short by design.

---

## Max Tokens Handling

When `stop_reason == "max_tokens"`, inject `{"role": "user", "content": "Continue where you left off."}` and continue. Do not return, do not crash, do not surface the truncation to the user.

---

## Stop Reasons We Handle

| `stop_reason` | Action |
|---|---|
| `end_turn` | Concatenate text blocks, return to caller. |
| `max_tokens` | Inject continuation prompt, continue loop. |
| `tool_use` (implicit) | Execute tools, feed results, continue loop. |
| anything else | Falls through to the tool-use branch. New stop reasons must be added explicitly if they require different handling. |
