# Chat Loop Invariants

> `chat(prompt, history)` and `handle_subagent` share the same agentic shape. This spec lists the invariants both must preserve.

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

Four-layer model. Layers 1 and 2 are size-based and share
`_persist_tool_result` (the disk-write + preview builder). Layer 3 is
count-based and clears contents in place. Layer 4 summarizes whole
history via LLM when token count nears the context window.

```
[turn N starts]
  microcompactMessages(history)                          # layer 3: count cap, whole history
  maybeAutoCompact(history)                              # layer 4: token cap, whole history (NEW)
  response = client.messages.create(...)
  _last_input_tokens = response.usage.input_tokens       # tracked for layer 4 (NEW)
  for each tool_use:
    content = maybePersistLargeToolResult(id, output)    # layer 1: per-result (>50K)
    results.append({tool_result, content})
  results = enforceToolResultBudget(results)             # layer 2: per-message (>200K total)
  _history_append(history, "user", results)
[turn N+1 starts]
```

Layers 3 and 4 run before the API call; layers 1 and 2 run after, on
the just-built results. Layer 4 uses real token data from the previous
response — no estimation, no tokenizer dependency, one-turn lag.

### Layer 1 — `maybePersistLargeToolResult` (per result)

Triggered per result when `len(output) > LARGE_TOOL_RESULT_THRESHOLD` (50K
chars). Writes the full output to disk, replaces with a ~2.2KB preview.

### Layer 2 — `enforceToolResultBudget` (per message)

Triggered per message when the sum of `len(content)` across all
`tool_result` blocks exceeds `TOOL_RESULT_MESSAGE_BUDGET` (200K chars).
Sorts results by content size descending and persists largest-first via
`_persist_tool_result` until the total fits.

Skip heuristic: results with `len(content) <= 2 * SUMMARY_HEAD_CHARS`
(4KB) are left alone — re-persisting would not shrink them (they may
already be Layer-1 summaries, or genuinely small). Since the iteration
is sorted by size descending, hitting one small result means all
remaining are also small, so the loop `break`s rather than `continue`s.

### Layer 3 — `microcompactMessages` (per turn, whole history)

Triggered per turn when the count of **uncleared compactable**
`tool_result` blocks exceeds `MICROCOMPACT_MAX_TOOL_RESULTS` (10). Leaves
the most recent `MICROCOMPACT_KEEP_RECENT` (5) uncleared compactable
blocks intact and replaces older ones' `content` with
`OLD_TOOL_RESULT_PLACEHOLDER` (`"[Old tool result content cleared]"`).

- **Uncleared** = `content != OLD_TOOL_RESULT_PLACEHOLDER`. Already-cleared
  blocks don't count toward the threshold; this batches compaction so it
  fires roughly every `MAX - KEEP_RECENT` turns instead of every turn.
- **Compactable** = tool name in `COMPACTABLE_TOOLS`
  (`{bash, read, write, edit, TodoWrite, skill}`). `run_subagent` is
  excluded — sub-agent outputs are one-shot and cannot be reproduced.
- Tool name is recovered from the matching `tool_use` block by scanning
  assistant messages for the `tool_use_id`.
- Whole body wrapped in `try/except` returning history unchanged on any
  failure; chat loop must never crash due to compaction.

### Layer 4 — `maybeAutoCompact` (per turn, whole history, LLM-based)

Triggered per turn when `_last_input_tokens > AUTOCOMPACT_THRESHOLD`
(default 150_000 = 200K window - 20K output reserve - 30K buffer).
`_last_input_tokens` is set by `chat()` from `response.usage.input_tokens`
after each API call — real data, no estimation.

When triggered, calls the model with a 9-section summary prompt and
the full history as input. On success, replaces history in place with
`[boundary_msg, summary_msg, *last_4_messages]`:

- **Boundary message**: user role, content `[compact_boundary]`. Goes
  through `_history_append` so it lands in transcript.
- **Summary message**: user role, content is a continuation prefix
  ("This session is being continued...") plus the LLM-generated summary,
  plus a pointer at `TRANSCRIPT_PATH` for full recovery. Also through
  `_history_append`.
- **Recent 4 messages**: references to the last 4 entries of the
  pre-compact history. Put back into history directly (NOT via
  `_history_append`) so they don't get double-written to transcript.

Short-circuits without work when:

- `_last_input_tokens <= AUTOCOMPACT_THRESHOLD`
- `len(history) < AUTOCOMPACT_KEEP_RECENT + 2`

Failures (network, 5xx, empty summary) print a yellow stderr notice
(`[Auto-compact failed: ...]`) and return False. History is untouched;
next turn will retry. `handle_subagent()` does NOT call
`maybeAutoCompact` — subagent tasks are short by design.

### Shared rules (Layers 1 and 2)

- File layout: `TOOL_RESULTS_DIR / <safe_id>.{txt|json}` where `TOOL_RESULTS_DIR = ~/.pyccode/projects/<sanitized-cwd>/<sessionId>/tool-results/`. Sibling of the transcript file (`<sanitized-cwd>/<sessionId>.jsonl`); never written inside `WORKDIR`.
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

Both `chat()` and `handle_subagent()` must run all three layers. Adding
a new agentic loop means inheriting the same contract.

---

## Transcript Logging

Every `history.append()` in `chat()` is mirrored to an append-only JSONL
file at `~/.pyccode/projects/<sanitized-cwd>/<SESSION_ID>.jsonl`. Write
side only — no resume logic in MVP.

### Mechanism

`_history_append(history, role, content)` is the single entry point for
both effects:

```python
def _history_append(history, role, content):
    history.append({"role": role, "content": content})
    appendTranscript(role, content)
```

Every site in `chat()` that used to call `history.append(...)` directly
now calls `_history_append(...)`. That covers: initial user prompt (with
skill metadata), assistant turns, tool-result user messages (post
`enforceToolResultBudget`), max-tokens continuation, and the TodoWrite
round-counter reminder.

### Schema (one JSON object per line)

| Field | Description |
|---|---|
| `type` | `"user"` or `"assistant"` (mirrors role) |
| `uuid` | Fresh `uuid4().hex` per entry |
| `parentUuid` | Previous entry's `uuid`, or `null` for the first |
| `timestamp` | ISO 8601 UTC |
| `sessionId` | `SESSION_ID` |
| `cwd` | `str(WORKDIR)` |
| `version` | `"0.1.0"` (reserved for future schema migrations) |
| `message` | The full `{"role": ..., "content": ...}` dict |

### Rules

- **Append-only.** Existing lines are never modified or deleted.
- **Open-write-close per entry.** No held file handle; each entry opens,
  writes, and closes the file. Trade-off: one syscall per append,
  negligible cost at chat-loop frequency.
- **Non-ASCII preserved verbatim.** `json.dumps(..., ensure_ascii=False)`
  so Chinese / emoji survive as-is, not as `\uXXXX` escapes.
- **Failure isolation.** `appendTranscript` wraps its body in
  `try/except`; on any failure it prints `[Transcript write failed: ...]`
  to **stderr** (not stdout) and returns. The in-memory
  `history.append()` has already happened; the chat loop continues.
- **Subagent exclusion.** `handle_subagent` uses its own local `messages`
  list and never calls `_history_append`, so subagent turns do not
  appear in the transcript. Future task will add separate
  `<sessionId>/subagents/` files.

### Interaction With `microcompactMessages`

`microcompactMessages` mutates in-memory `history` in place but does
not call `history.append()`, so it produces no transcript entries. Old
tool_result entries already written to transcript keep their full
original content; the placeholder substitution lives only in memory.
Future resume work must add `content-replacement` entries (or
equivalent) to preserve microcompact's effect across sessions. See the
transcript-logging task's design doc for details.

### Future Optimization (deferred)

Layer 1's `~/.pyccode/projects/<sanitized-cwd>/<sessionId>/tool-results/<id>.{txt|json}`
files could be replaced by "recovery pointers" into the transcript
(changing the write order to "transcript first, then summary"). Single
source of truth for conversation history. Out of scope for MVP.

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

Applied in `chat()` and `handle_subagent`. When adding a new injection point, mirror this exact wrapper.

---

## Round-Counter Reminder (main agent only)

After 5 consecutive tool-use rounds without a `TodoWrite` call, `chat()` injects a user message nudging the model to plan. Counter resets to 0 on any `TodoWrite` call.

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
