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

Before appending a `tool_result`:

```python
"content": maybePersistLargeToolResult(content.id, output)
```

`output[:50000]` style hard truncation is forbidden — it silently drops the tail with no recovery path. See `maybePersistLargeToolResult` at pyccode.py:559.

- Threshold: `LARGE_TOOL_RESULT_THRESHOLD = 50000` chars.
- Over threshold: full output goes to `WORKDIR / SESSION_ID / "tool-results" / <safe_id>.{txt|json}`, summary (~2KB head-only) goes to the API.
- Extension sniffed via `json.loads` — `.json` if valid, otherwise `.txt`.
- Summary intentionally does not name a downstream tool. The agent decides how to inspect the file (`read`, `grep`, `bash`).
- On filesystem failure: fall back to legacy 50K truncation with `[persist failed: <error>]` appended. Never raise.

Both `chat()` and `handle_subagent()` must call this helper. Adding a new agentic loop means inheriting the same contract.

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
