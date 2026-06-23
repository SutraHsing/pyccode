# Design — Move tool-results/ next to transcript under ~/.pyccode/

## Architecture

One path constant changes. Both layers inherit.

```
TRANSCRIPT_DIR = Path.home() / ".pyccode" / "projects"
TRANSCRIPT_CWD = re.sub(r'[^A-Za-z0-9._-]', '-', str(WORKDIR))
TRANSCRIPT_PATH = TRANSCRIPT_DIR / TRANSCRIPT_CWD / f"{SESSION_ID}.jsonl"

# NEW
TOOL_RESULTS_DIR = TRANSCRIPT_DIR / TRANSCRIPT_CWD / SESSION_ID / "tool-results"
```

`_persist_tool_result` writes to
`TOOL_RESULTS_DIR / f"{safe_id}.{ext}"` instead of
`WORKDIR / SESSION_ID / "tool-results" / f"{safe_id}.{ext}"`.

## Directory Layout After Change

```
~/.pyccode/
└── projects/
    └── <sanitized-cwd>/              # e.g. -Users-sutra-PycharmProjects-pyccode
        ├── <SESSION_ID>.jsonl        # transcript (existing)
        └── <SESSION_ID>/             # NEW dir for session artifacts
            └── tool-results/
                ├── toolu_abc123.txt
                └── toolu_def456.json
```

The `<SESSION_ID>` coexists as both a file stem (`.jsonl`) and a
directory name. Filesystems allow this. Matches Claude Code's layout.

## Constant Naming

`TOOL_RESULTS_DIR` derives cleanly from existing constants:

```python
TRANSCRIPT_DIR = Path.home() / ".pyccode" / "projects"
TRANSCRIPT_CWD = re.sub(r'[^A-Za-z0-9._-]', '-', str(WORKDIR))
TRANSCRIPT_PATH = TRANSCRIPT_DIR / TRANSCRIPT_CWD / f"{SESSION_ID}.jsonl"
TOOL_RESULTS_DIR = TRANSCRIPT_DIR / TRANSCRIPT_CWD / SESSION_ID / "tool-results"
```

All four constants share the `~/.pyccode/projects/<sanitized-cwd>/`
prefix, so they stay in sync if we ever change the root.

## `_persist_tool_result` Changes

Before (current):

```python
safe_id = re.sub(r'[^A-Za-z0-9_-]', '_', tool_use_id)
result_dir = WORKDIR / SESSION_ID / "tool-results"
result_dir.mkdir(parents=True, exist_ok=True)
file_path = result_dir / f"{safe_id}.{ext}"
file_path.write_text(output, encoding='utf-8')
```

After:

```python
safe_id = re.sub(r'[^A-Za-z0-9_-]', '_', tool_use_id)
TOOL_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
file_path = TOOL_RESULTS_DIR / f"{safe_id}.{ext}"
file_path.write_text(output, encoding='utf-8')
```

Three lines change. The summary builder and stdout notice use the
local `file_path` variable, so they automatically reflect the new
location without further edits.

## Summary Format

Unchanged. Still:

```
[tool_result_persisted]
original_length: 100000 chars
persisted_to: /Users/<user>/.pyccode/projects/<sanitized-cwd>/<sessionId>/tool-results/toolu_xxx.txt

--- HEAD ---
...
--- end ---
```

Only the path value changes (now under `~/.pyccode/...` instead of
`<WORKDIR>/...`). The agent uses the existing `read` tool on the path
to recover full content. No prompt change needed.

## Why Not Merge Into Transcript

Reconsidered and rejected for this task. Reasons:

1. **MVP simplicity**: merging requires schema additions
   (`raw_tool_result` entries), recovery logic on the agent side
   (grep + jq), and careful write ordering. All for marginal benefit.
2. **Single-purpose files**: a file-per-tool-result makes `read` tool
   recovery dead simple — agent just `read`s the path in the summary.
   No JSON parsing.
3. **Layout parity with Claude Code**: their design separates
   transcript (chat log) from tool-results (large blobs) too. Same
   mental model.
4. **Future flexibility**: if we later want to add compression /
   encryption / retention to large blobs, having them as separate
   files is easier than picking lines out of a JSONL.

The "merge into transcript" optimization stays noted as future work
in the transcript-logging task's design.md.

## Why Not Separate Layer 1 From Layer 2

Claude Code distinguishes them: Layer 1 writes files at generation
time, Layer 2 records `content-replacement` entries post-hoc because
it mutates already-written transcript lines.

pyccode doesn't have that problem. Both layers run **before** the user
message is appended to history/transcript. Both call the same
`_persist_tool_result` helper. There's no need for a separate
mechanism — the file path is identical, the summary format is
identical, the only difference is the trigger condition (size vs
aggregate budget).

Keeping one helper means one place to fix bugs, one path constant,
one set of failure semantics.

## Failure Modes

| Scenario | Behavior |
|---|---|
| First write of session | `mkdir(parents=True)` creates the chain `~/.pyccode/projects/<sanitized-cwd>/<sessionId>/tool-results/`. |
| Disk full mid-write | `write_text` raises; caught by outer try/except; legacy 50K truncation returned. |
| Permission denied on `~/.pyccode/` | `mkdir` or `write_text` raises; same fallback. |
| `safe_id` collision (same tool_use_id reused) | File overwritten — no crash. Anthropic IDs are unique per call so unlikely. |

## Trade-offs

- **One new directory level**: `<SESSION_ID>/tool-results/` instead of
  `<SESSION_ID>/` directly. Costs one path segment; gains future
  extensibility (can add `<SESSION_ID>/subagents/`, `<SESSION_ID>/cache/`,
  etc. without restructuring).
- **No automatic cleanup of old `WORKDIR/<sessionId>/` dirs**: those
  stay where they are. User must `rm -rf` manually. Old summaries
  referencing old paths work until files are deleted.
- **Coexisting file + directory with same `<sessionId>` stem**: slightly
  unusual but filesystem-legal. Matches Claude Code's layout, so users
  familiar with that convention won't be surprised.

## Compatibility

- No external API change.
- No settings / env var change.
- No on-disk format change.
- One new directory location under `~/.pyccode/`.
- Old `WORKDIR/<sessionId>/tool-results/` directories linger until
  manual cleanup; not migrated.
- Spec updates needed: chat-loop.md (path examples), directory-structure.md
  (project layout drops the in-project `<sessionId>/` line).
