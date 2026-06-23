# Move tool-results/ next to transcript under ~/.pyccode/

## Goal

Relocate the large-tool-result files written by `_persist_tool_result`
from `WORKDIR/<sessionId>/tool-results/` (project directory — pollutes
the user's repo, shows up in `git status`, gets committed by accident)
to `~/.pyccode/projects/<sanitized-cwd>/<sessionId>/tool-results/`
(sibling of the transcript file, under the user's home, never touches
the project).

## Background

Today `_persist_tool_result` writes to:

```
<WORKDIR>/<SESSION_ID>/tool-results/<safe_id>.{txt|json}
```

`WORKDIR = Path.cwd()` so this lands inside the user's project. Every
time the agent reads a large file or runs a chatty bash command, a
`<SESSION_ID>/` directory appears in the project root. Users have to
`.gitignore` it manually or risk committing it.

The transcript file already lives under `~/.pyccode/projects/`:

```
~/.pyccode/projects/<sanitized-cwd>/<SESSION_ID>.jsonl
```

Claude Code's layout puts large outputs in a sibling directory:

```
~/.claude/projects/<sanitized-cwd>/<session-id>/tool-results/<id>.txt|json
```

Adopting the same convention here keeps everything pyccode writes
under one root, never in the project.

Layer 1 (`maybePersistLargeToolResult`) and Layer 2
(`enforceToolResultBudget`) both call `_persist_tool_result`, so moving
the path in one place moves both. No Claude-Code-style separation
between the two layers — pyccode uses a single shared helper and that's
fine.

## Requirements

### Functional

- `_persist_tool_result` writes to
  `~/.pyccode/projects/<sanitized-cwd>/<sessionId>/tool-results/<safe_id>.<ext>`
  instead of `WORKDIR/<sessionId>/tool-results/<safe_id>.<ext>`.
- `<sanitized-cwd>` matches the existing `TRANSCRIPT_CWD` constant
  (collapses non-`[A-Za-z0-9._-]` to `-`), so tool-results land next to
  the transcript file under the same per-project directory.
- `<sessionId>` directory is created on first write
  (`mkdir(parents=True, exist_ok=True)`).
- Summary format is unchanged — still says
  `persisted_to: <absolute file path>`. The path value just changes
  location.
- All other behavior (extension sniff, id sanitize, head slice, error
  fallback) is unchanged.
- Layer 1 and Layer 2 share `_persist_tool_result`, so both pick up the
  new location automatically.

### Non-functional

- One constant change (introduce `TOOL_RESULTS_DIR` or derive from
  existing `TRANSCRIPT_DIR`).
- No new functions.
- No new external dependencies.
- Backwards compatibility: any `WORKDIR/<sessionId>/tool-results/`
  directories from previous sessions stay where they are. Old
  summaries referencing old paths still work until the user manually
  cleans up.

## Acceptance Criteria

- [ ] After a tool result > 50K chars, the persisted file appears at
      `~/.pyccode/projects/<sanitized-cwd>/<sessionId>/tool-results/<id>.{txt|json}`.
- [ ] No directory is created in `WORKDIR` (the project root) for
      session-scoped artifacts anymore.
- [ ] The summary returned to the chat loop contains the new absolute
      path under `~/.pyccode/...` in its `persisted_to:` line.
- [ ] A summary written this session, when its `persisted_to:` path is
      passed to the `read` tool, returns the full original content.
- [ ] `enforceToolResultBudget`-persisted results land in the same
      directory as Layer 1 results.
- [ ] Disk-write failure at the new location still triggers the
      `[persist failed: ...]` fallback; chat loop is unaffected.
- [ ] On a fresh process, the first large result creates the full
      directory chain (`~/.pyccode/projects/<sanitized-cwd>/<sessionId>/tool-results/`)
      without errors.

## Out of Scope

- Cleaning up old `WORKDIR/<sessionId>/tool-results/` directories from
  past sessions (user can `rm -rf` manually).
- Migrating existing summaries to point at new paths.
- Merging tool-results into the transcript file (deferred — see
  transcript-logging task's "Future Optimization" section in its
  design.md).
- Adding content-replacement entries to transcript (Claude Code style).
- Compression / encryption / retention policy for persisted files.
- Subagent transcripts.
