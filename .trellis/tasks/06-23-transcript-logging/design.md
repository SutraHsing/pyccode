# Design — Add transcript JSONL logging for main agent

## Architecture

One new module-level helper writes a JSONL entry per
`history.append()`. Call sites in `chat()` are migrated to a thin
wrapper that does both the in-memory append and the transcript write.

```
chat()                                    handle_subagent()
  │                                         │
  ├─ _history_append(history, role, content)│  (not transcribed — MVP)
  │     ├─ history.append(...)
  │     └─ appendTranscript(role, content)
  │
  └─ ...rest of loop unchanged...          └─ messages.append(...) unchanged
```

Subagent is naturally excluded: it uses its own local `messages` list,
which is never passed to `_history_append`.

## Module Constants

```python
from datetime import datetime, timezone

TRANSCRIPT_VERSION = "0.1.0"
TRANSCRIPT_DIR = Path.home() / ".pyccode" / "projects"
TRANSCRIPT_CWD = re.sub(r'[^A-Za-z0-9._-]', '-', str(WORKDIR))
TRANSCRIPT_PATH = TRANSCRIPT_DIR / TRANSCRIPT_CWD / f"{SESSION_ID}.jsonl"
```

Sanitization collapses anything outside `[A-Za-z0-9._-]` to `-`. For
`/Users/sutra/PycharmProjects/pyccode` →
`-Users-sutra-PycharmProjects-pyccode`.

## State

Module-level chain tracker:

```python
_transcript_last_uuid: str | None = None
```

- `None` at process start (no entries yet).
- Updated to the freshly-generated `uuid` after every successful write.
- Read by the next `appendTranscript()` call to set `parentUuid`.

REPL-safe: the variable persists across `chat()` calls because it lives
at module scope. Each `chat()` call continues the chain.

## Functions

### `appendTranscript(role, content)`

```python
def appendTranscript(role: str, content) -> None:
    """Append one entry to the session transcript JSONL file.

    Writes a single JSON object on its own line. Updates the module-level
    ``_transcript_last_uuid`` to form a parent chain. Never raises:
    transcript failures must not break the chat loop.
    """
    global _transcript_last_uuid
    try:
        entry_uuid = uuid.uuid4().hex
        entry = {
            "type": role,
            "uuid": entry_uuid,
            "parentUuid": _transcript_last_uuid,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "sessionId": SESSION_ID,
            "cwd": str(WORKDIR),
            "version": TRANSCRIPT_VERSION,
            "message": {"role": role, "content": content},
        }
        TRANSCRIPT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(TRANSCRIPT_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        _transcript_last_uuid = entry_uuid
    except Exception as e:
        print(f"\033[33m[Transcript write failed: {e}]\033[0m", file=sys.stderr)
```

Design notes:

- **Open / write / close per entry**: no held fd, crash-safe, simpler
  lifecycle. The cost (one `open()` per `history.append()`) is
  negligible — appends happen at most a few times per turn.
- **`ensure_ascii=False`**: non-ASCII content survives verbatim instead
  of being escaped to `\uXXXX`. JSONL stays readable.
- **`mkdir(parents=True, exist_ok=True)`** inside the `try`: cheap and
  handles first-write bootstrapping.
- **Failure path**: print yellow notice to **stderr** (stdout is
  reserved for handler output per logging-guidelines), keep going. The
  caller's `history.append()` has already happened or is about to —
  either way the in-memory conversation is unaffected.

### `_history_append(history, role, content)`

```python
def _history_append(history: list, role: str, content) -> None:
    """Append a message to history and mirror it to the transcript."""
    history.append({"role": role, "content": content})
    appendTranscript(role, content)
```

Private (leading `_`) — internal helper, not part of any external
contract. Replaces the literal `history.append({"role": ..., "content":
...})` calls inside `chat()`.

## Integration Points in `chat()`

There are five `history.append(...)` call sites in `chat()`. All get
migrated:

| Site | Current | After |
|---|---|---|
| Initial user prompt | `history.append({"role": "user", "content": prompt})` | `_history_append(history, "user", prompt)` |
| Assistant turn | `history.append({"role": "assistant", "content": assistant_content})` | `_history_append(history, "assistant", assistant_content)` |
| Tool results | `history.append({"role": "user", "content": enforceToolResultBudget(results)})` | `_history_append(history, "user", enforceToolResultBudget(results))` |
| max-tokens continuation | `history.append({"role": "user", "content": "Continue where you left off."})` | `_history_append(history, "user", "Continue where you left off.")` |
| TodoWrite reminder | `history.append({"role": "user", "content": "Reminder: ..."})` | `_history_append(history, "user", "Reminder: ...")` |

`handle_subagent()` keeps `messages.append(...)` unchanged — its local
list never goes through `_history_append`, so subagent stays
un-transcribed in MVP.

## Why parentUuid From Day One

Linear conversations are just a linked list. Adding `parentUuid` now
costs ~3 lines (one variable, one assignment, one field). Retrofitting
it later would require:

1. Re-running every old transcript through a migration to synthesize
   UUIDs.
2. Deciding parent semantics for entries that already exist without
   them.

Better to pay the small cost now. Future resume logic can rebuild the
chain from the leaf backward, robust against partial writes or
reordering.

## Failure Modes

| Scenario | Behavior |
|---|---|
| First write of session | `mkdir(parents=True)` creates the dir; file is created on `open(..., "a")`. |
| Disk full mid-write | `open()` or `f.write()` raises `OSError`; caught; yellow notice printed; `_transcript_last_uuid` not updated (so next entry's `parentUuid` is the last successfully-written uuid — chain stays consistent with what's actually on disk). |
| Permission denied on dir | `mkdir` or `open` raises; caught; yellow notice; chat loop continues. |
| `content` not JSON-serializable | `json.dumps` raises `TypeError`; caught; yellow notice. Should never happen with our message shapes but defensive. |
| Process killed mid-write | Last line may be partial — JSONL readers typically tolerate this by skipping unparseable lines. Acceptable for MVP. |

## Trade-offs

- **Write-only MVP**: no read/resume. Schema is forward-compatible;
  adding a reader later is a new task, not a migration.
- **Sync writes per entry**: simple, crash-safe. Cost: one `open()` per
  append. Acceptable for chat-loop append frequency (a handful per
  turn).
- **Module-level `_transcript_last_uuid`**: not thread-safe. pyccode is
  single-threaded so this is fine. If we ever go async, wrap in a
  lock or thread-local.
- **No rotation**: a long-running REPL session could grow the file
  without bound. Defer — `~/.pyccode/projects/<cwd>/` is per-session so
  individual files stay bounded by one session's length.
- **No encryption / redaction**: secrets in prompts or tool outputs
  land in plaintext on disk. Matches Claude Code's behavior; documented
  as a known limitation.

## Compatibility

- No external API change.
- No settings / env var change.
- One new on-disk artifact: `~/.pyccide/projects/<sanitized-cwd>/<sessionId>.jsonl`.
- Conversation history semantics in memory: unchanged. Transcript is a
  pure side-effect of `history.append()`.

## Interaction With microcompactMessages

`microcompactMessages` mutates in-memory `history` — it replaces old
tool_result `content` fields with `OLD_TOOL_RESULT_PLACEHOLDER` in
place. It does **not** call `history.append()`, so it does not produce
new transcript entries.

Because transcript is append-only and never modifies existing lines:

- Old tool_result entries already written to JSONL keep their **full
  original content**. They are not retroactively replaced with the
  placeholder.
- The placeholder substitution lives only in the in-memory history
  after microcompact runs; if a future turn appends a message that
  quotes or references the compacted tool_result, the appended message
  sees the placeholder (because that's what's in memory at append
  time).

Implication for future resume: a naive "read all lines and rebuild
history" loader would restore the **original** full content for old
tool_results, not the placeholder. This is the opposite of what
microcompact intended. Claude Code solves this with explicit
`content-replacement` metadata entries. **MVP does not** — resume is
explicitly out of scope. When resume becomes a real task, that task
must add the replacement entries (or another mechanism) to keep the
microcompact effect persistent across sessions.

## Future Optimization (deferred — recorded for later)

Once transcript logging is in place, the `WORKDIR/<sessionId>/tool-results/<id>.{txt|json}`
files written by Layer 1 (`maybePersistLargeToolResult`) become
redundant as a recovery source — the original content can be recovered
from the transcript if we change the write order to "transcript first,
then Layer 1 summary".

A future task could:

1. Write the original tool_result content to transcript **before**
   applying Layer 1 (today the order is reversed — summary is what
   lands in transcript).
2. Replace Layer 1's `tool-results/<id>.txt` file write with a
   "recovery pointer" in the summary: e.g. `recover_from:
   transcript:<uuid>` instead of `persisted_to: <file-path>`.
3. Add a reader helper that, given a transcript UUID, returns the
   original content from the JSONL.

Benefits: removes a whole on-disk artifact class, single source of
truth for conversation history, simpler mental model.

Costs: transcript files get larger (they absorb what was in
`tool-results/`); JSONL line lengths could exceed practical grep
limits; resume logic becomes coupled to transcript parsing rather than
plain file reads.

**MVP does not do this.** The current Layer 1 + transcript design
works fine; this is a noted future simplification, not an open
problem.
