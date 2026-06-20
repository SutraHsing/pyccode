# Design — Persist large tool results

## Architecture

Single-file addition to `pyccode.py`. No new modules, no new dependencies.
One helper function plus three integration points: a constants block, the two
tool-result sites (`chat()` and `handle_subagent()`), and process-exit cleanup.

## Module-level Constants

Add to the top of `pyccode.py` alongside `WORKDIR = Path.cwd()`:

```python
import json
import uuid

WORKDIR = Path.cwd()
SESSION_ID = uuid.uuid4().hex
LARGE_TOOL_RESULT_THRESHOLD = 50000   # chars
SUMMARY_BUDGET = 2048                  # chars (entire budget goes to head + metadata)
```

## Function Signature

```python
def maybePersistLargeToolResult(tool_use_id: str, output: str) -> str:
    ...
```

- Pure except for one filesystem write + one stdout print.
- On filesystem failure, falls back to legacy `output[:LARGE_TOOL_RESULT_THRESHOLD]`
  with an error note appended. The chat loop must never crash because of persistence.

## Extension Sniffing

```python
try:
    json.loads(output)
    ext = "json"
except (ValueError, TypeError):
    ext = "txt"
```

`json.JSONDecodeError` subclasses `ValueError`, so the broad catch is correct.
`TypeError` is defensive against the impossible case where `output` is not a str.

## Filename Safety

```python
safe_id = re.sub(r'[^A-Za-z0-9_-]', '_', tool_use_id)
```

Anthropic tool_use IDs look like `toolu_01ABC...` and are already safe. The
regex is cheap insurance against upstream format changes.

## Directory Layout

```
<WORKDIR>/
  <SESSION_ID>/              # uuid4 hex, e.g. 7c5e...
    tool-results/
      toolu_01ABC.txt        # one file per oversized tool_use
      toolu_02DEF.json
```

Parents are created with `mkdir(parents=True, exist_ok=True)`.

## Summary Format

```
[tool_result_persisted]
original_length: 123456 chars
persisted_to: /Users/sutra/.../tool-results/toolu_xxx.txt

--- HEAD (first 2000 chars) ---
<head>
--- end ---
```

The head budget is `SUMMARY_BUDGET` (2048) minus the metadata overhead. The
final string is clamped to `SUMMARY_BUDGET` as a safety net. The summary
intentionally does not name a downstream tool — the agent picks how to inspect
the file (`read` for line ranges, `grep` for patterns, `bash` with `awk`/`sed`
for structured queries).

## Integration Points

### `chat()` (pyccode.py:641-645)

Before:
```python
results.append({
    "type": "tool_result",
    "tool_use_id": content.id,
    "content": output[:50000]
})
```

After:
```python
results.append({
    "type": "tool_result",
    "tool_use_id": content.id,
    "content": maybePersistLargeToolResult(content.id, output),
})
```

### `handle_subagent()` (pyccode.py:534-538)

Same replacement. `SESSION_ID` is shared with the main agent, so subagent
persisted files land in the same directory.

### Process Exit

No atexit cleanup. Each session writes under its own UUID-named directory, so
runs do not collide. Files stay on disk for post-session inspection; the user
cleans up old session dirs manually when desired.

## Persisted File Access

The persisted file is plain UTF-8. The agent can use any existing tool to
inspect it — `read` (line ranges), `bash` (`grep`, `awk`, `sed`, `head`,
`tail`), or anything else. The summary only prints the path; it does not
prescribe a tool, so the agent can choose the most token-efficient approach
for the situation (e.g. `grep` for a pattern rather than re-reading the whole
file).

## Failure Modes

| Scenario | Behavior |
|---|---|
| Disk full / permission denied | Fall back to legacy 50K truncation, append `[persist failed: <error>]` |
| `tool_use_id` collision (same id reused) | File is overwritten — no crash. Anthropic IDs are unique per call. |
| Binary-ish output with invalid UTF-8 | Already sanitized upstream by handlers (`errors='replace'`). |
| Very long single-line JSON | Write completes; read returns one giant line. |

## Trade-offs

- **Project-local storage, no auto-cleanup**: chosen for inspectability during
  and after the session. Cost: project dir accumulates `<sessionId>/`
  subdirectories across runs; user cleans up manually. Each session uses its
  own UUID dir so concurrent or successive runs never collide.
- **Head-only summary**: simpler and the head is usually the most informative
  part (error headers, first lines of output). No tail snippet means the
  summary cannot show trailing stack traces; the agent can read the end of the
  file via `tail`/`read` if needed.
- **Full content to file vs overflow only**: full content lets the agent use
  any tool with arbitrary offset/limit. Cost: disk proportional to actual
  output size.
- **JSON sniff via `json.loads`**: cheap (only runs on >50K strings), correct
  for well-formed JSON. Malformed JSON falls through to `.txt`, which is fine.

## Compatibility

- No external API change.
- No settings/env var change.
- Conversation history semantics: tool_result `content` is now either the raw
  output (< threshold) or a summary string (> threshold). Both are strings,
  which the Anthropic API accepts in `tool_result.content`.
