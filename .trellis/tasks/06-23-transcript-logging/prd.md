# Add transcript JSONL logging for main agent

## Goal

Persist every main-agent conversation message to an append-only JSONL
file so that past sessions can be inspected, debugged, and (in a future
task) resumed.

## Background

pyccode currently keeps conversation history in memory only — restart
loses everything. Claude Code's transcript design shows the proven
shape: append-only JSONL under `~/.claude/projects/<sanitized-cwd>/<session-uuid>.jsonl`,
one JSON object per line, with a `parentUuid` chain for robust future
recovery.

This task lands the **write side only**. Resume / search / compact
boundaries / subagent transcripts are explicitly out of scope — the
schema is shaped to accept them later without migration, but the MVP
just appends one line per `history.append()`.

## Requirements

### Functional

- Every main-agent `history.append(...)` in `chat()` is mirrored to a
  transcript JSONL file. That covers: initial user prompt (with skill
  metadata injection), assistant turns, tool_result user messages
  (after `enforceToolResultBudget`), max-tokens "Continue where you left
  off." injections, and the TodoWrite round-counter reminder.
- Subagent (`handle_subagent`) is **not** transcribed in MVP. Its
  isolated `messages` list is unaffected.
- Transcript path:
  `~/.pyccode/projects/<sanitized-cwd>/<SESSION_ID>.jsonl` where
  `<sanitized-cwd>` collapses non-`[A-Za-z0-9._-]` chars in
  `str(WORKDIR)` to `-`. The directory is created with
  `mkdir(parents=True, exist_ok=True)` on first write.
- Each line is a JSON object with these fields:
  - `type`: `"user"` or `"assistant"` (mirrors message role)
  - `uuid`: fresh `uuid.uuid4().hex` per entry
  - `parentUuid`: the previous entry's `uuid`, or `null` for the first
    entry in the session
  - `timestamp`: ISO 8601 UTC (`datetime.now(timezone.utc).isoformat()`)
  - `sessionId`: `SESSION_ID`
  - `cwd`: `str(WORKDIR)`
  - `version`: `"0.1.0"` (literal for now; reserved for future schema
    migrations)
  - `message`: the full `{"role": ..., "content": ...}` dict that was
    appended to `history`
- Writes are synchronous and append-only. Open / write / close per
  entry — no held file handle. UTF-8, `ensure_ascii=False` so non-ASCII
  content survives verbatim.
- REPL mode continues writing to the same file across turns (the
  session ID is process-level; the file grows across REPL iterations).
- Transcript failures (disk full, permission denied, serialization
  error) must not break the chat loop. On failure, print a yellow
  notice to stderr and continue — the in-memory `history.append()`
  still happens.

### Non-functional

- One new module-level function `appendTranscript(role, content)`.
- One new module-level helper that wraps `history.append()` +
  `appendTranscript(...)` so call sites in `chat()` stay one line.
- Module-level `_transcript_last_uuid` tracks the chain.
- No new external dependencies.

## Acceptance Criteria

- [ ] After a single-prompt run (`python pyccode.py "..."`), the file
      `~/.pyccode/projects/<sanitized-cwd>/<sessionId>.jsonl` exists and
      contains one line per `history.append()` call, in order.
- [ ] Each line parses as JSON and contains all required fields.
- [ ] `parentUuid` of entry N equals `uuid` of entry N-1; the first
      entry's `parentUuid` is `null`.
- [ ] Non-ASCII content (e.g. Chinese user prompt) survives verbatim in
      the JSONL.
- [ ] REPL mode: consecutive `chat()` calls append to the same file;
      `parentUuid` chains across turns.
- [ ] Disk write failure (simulate via `chmod 000` on the directory)
      does not crash the chat loop; a yellow notice is printed to
      stderr and the conversation proceeds.
- [ ] Subagent invocations do not produce transcript entries.
- [ ] Transcript file is valid JSONL: `jq -c . <file>` exits 0.

## Out of Scope

- Reading / resuming from transcript (future task).
- Compact boundary entries (no full compact in pyccode yet).
- `content-replacement` entries — MVP's transcript is append-only, so
  old tool_result entries keep their full content even after
  `microcompactMessages` replaces them in memory with the placeholder.
  Future resume work must add replacement entries (or equivalent) to
  preserve microcompact's effect across sessions. See design.md
  "Interaction With microcompactMessages".
- Metadata entries (`custom-title`, `tag`, `last-prompt`).
- Subagent transcripts (separate file under `<sessionId>/subagents/`,
  future task).
- Search / indexing.
- Streaming-aware writes (pyccode does not stream).
