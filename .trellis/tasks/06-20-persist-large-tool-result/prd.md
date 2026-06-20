# Persist large tool results to temp file

## Goal

Avoid silently losing tool output beyond the 50K char hard cap. When a tool
result exceeds the threshold, persist the full content to a file and replace
the in-conversation content with a compact summary, so the model retains a
pointer to recover the full output via the `read` tool.

## Background

Today, both `chat()` (pyccode.py:644) and `handle_subagent()` (pyccode.py:537)
truncate tool results with `output[:50000]` and discard the rest. For commands
or reads that produce large outputs (log dumps, big files, large JSON), the
model loses information with no way to recover it.

## Requirements

### Functional

- New function `maybePersistLargeToolResult(tool_use_id, output) -> str`:
  - If `len(output) <= 50000`: return `output` unchanged.
  - Else: write the full `output` to
    `WORKDIR / SESSION_ID / "tool-results" / <safe_id>.<ext>`,
    and return a summary string (~2KB) that includes a head snippet, the
    original length, and the persisted file path.
- Extension is `.json` if `output` parses as valid JSON via `json.loads`;
  otherwise `.txt`.
- Sanitize `tool_use_id` so only `[A-Za-z0-9_-]` characters remain in the
  filename.
- Both the main agent and the subagent call the new function in place of
  `output[:50000]`.
- `SESSION_ID` is a process-level UUID4 hex string, generated once at module
  load and shared between the main agent and all subagents.
- A short notice is printed to stdout when a result is persisted.
- A persistence failure (disk error, permission denied) must not break the
  chat loop: fall back to the legacy 50K truncation with an error note.
- The summary must not prescribe a specific tool for accessing the persisted
  file. The agent decides how to inspect it (e.g. `read` for line ranges,
  `grep` for patterns, `bash` with `awk`/`sed` for structured queries).

### Non-functional

- Summary stays within ~2KB under all inputs.
- No network calls; pure local file I/O.
- No new external dependencies.

## Acceptance Criteria

- [ ] A tool result with 50000 chars or fewer is returned to the API unchanged.
- [ ] A tool result larger than 50000 chars triggers a write to
      `WORKDIR/<sessionId>/tool-results/<tool_use_id>.<ext>` and the API
      receives a summary referencing that path.
- [ ] The summary contains a head snippet of ~2KB (no tail), the original
      length, and the persisted file path — and does not name any specific
      downstream tool.
- [ ] JSON-shaped outputs persist with `.json` extension; plain text with `.txt`.
- [ ] The main agent (`chat()`) and subagent (`handle_subagent()`) both use
      the new helper and share the same session directory.
- [ ] Persisted files remain on disk after the process exits (no auto-cleanup);
      each session uses its own UUID-named directory so runs do not collide.

## Out of Scope

- Configurable threshold / summary budget (constants are fine for MVP).
- Persisting to OS temp dir or remote storage.
- Compressing persisted content.
- Migrating existing in-flight conversation histories.
