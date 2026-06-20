# Design — Enforce tool result budget per message

## Architecture

Layered with the existing per-result persistence. The two passes share a
private helper that does the actual file write + preview build.

```
chat() / handle_subagent()
  for each tool_use:
    output = handler(...)
    content = maybePersistLargeToolResult(id, output)   # per-result pass (>50K)
    results.append({tool_result, content})
  results = enforceToolResultBudget(results)             # per-message pass (>200K total)
  history.append({role: user, content: results})
```

Per-result runs first because it has the strictest threshold and produces
stable ~2.2KB summaries. Per-message runs second to clean up "many medium
results" cases.

## Refactor: extract `_persist_tool_result`

Pull the body of `maybePersistLargeToolResult` (everything after the
threshold short-circuit) into a private helper:

```python
def _persist_tool_result(tool_use_id: str, output: str) -> str:
    """Write output to disk and return the preview summary.

    Caller decides whether persistence is warranted (threshold or budget).
    Never raises: on filesystem failure, returns legacy truncation with
    an error note.
    """
    try:
        <json sniff, sanitize id, mkdir, write_text, build summary, print>
        return summary
    except Exception as e:
        return output[:LARGE_TOOL_RESULT_THRESHOLD] + f"\n[persist failed: {e}]"
```

`maybePersistLargeToolResult` becomes a thin size-check wrapper:

```python
def maybePersistLargeToolResult(tool_use_id: str, output: str) -> str:
    if len(output) <= LARGE_TOOL_RESULT_THRESHOLD:
        return output
    return _persist_tool_result(tool_use_id, output)
```

No behavior change for existing callers.

## New Constant

```python
TOOL_RESULT_MESSAGE_BUDGET = 200_000   # chars (approx 200KB for ASCII)
```

Char count is a proxy for byte count. Close enough for budget enforcement;
off by at most a small constant factor for multibyte UTF-8.

## Algorithm

```python
def enforceToolResultBudget(results: list[dict]) -> list[dict]:
    total = sum(len(r["content"]) for r in results)
    if total <= TOOL_RESULT_MESSAGE_BUDGET:
        return results

    # Largest-first. Sort indices so we can mutate in place.
    order = sorted(
        range(len(results)),
        key=lambda i: len(results[i]["content"]),
        reverse=True,
    )
    for i in order:
        if total <= TOOL_RESULT_MESSAGE_BUDGET:
            break
        content = results[i]["content"]
        # Skip already-small results — persisting won't shrink them.
        if len(content) <= 2 * SUMMARY_HEAD_CHARS:
            continue
        new_content = _persist_tool_result(results[i]["tool_use_id"], content)
        total += len(new_content) - len(content)
        results[i] = {**results[i], "content": new_content}
    return results
```

Mutation strategy: in-place replacement of `content` keeps `tool_use_id`
and `type` fields intact. Using `{**r, "content": new_content}` creates a
new dict per change, which is safer than mutating during iteration.

## Skip Heuristic

`if len(content) <= 2 * SUMMARY_HEAD_CHARS: continue`

- A result already at preview size (2.2KB) yields no savings — skip.
- A result at 4KB yields ~1.8KB savings — marginal but worth it when we
  are near budget.
- The check naturally handles results already summarized by the
  per-result pass: those are ~2.2KB, well under 4KB, so skipped.

## Integration Points

### `chat()` (pyccode.py:~703)

Current shape:

```python
results = []
for content in response.content:
    if content.type == "tool_use":
        ...
        results.append({
            "type": "tool_result",
            "tool_use_id": content.id,
            "content": maybePersistLargeToolResult(content.id, output),
        })

history.append({"role": "user", "content": results})
```

After:

```python
results = []
for content in response.content:
    if content.type == "tool_use":
        ...
        results.append({...})  # per-result pass already applied above

results = enforceToolResultBudget(results)
history.append({"role": "user", "content": results})
```

### `handle_subagent()` (pyccode.py:~540)

Same insertion point: between building `results` and appending to
`messages`.

## Edge Cases

| Scenario | Behavior |
|---|---|
| Empty `results` list | `total = 0`, returns unchanged. |
| One result, total over budget | Already handled by per-result pass; budget pass finds it small, skips, leaves it. |
| All results already small (post per-result pass) | Skip-everyone, return as-is. Total may still be over budget — acceptable (no further wins available). |
| One persist raises | `_persist_tool_result` catches internally, returns legacy truncation string. Loop continues. |
| Two results tie for largest | Sort is stable; ties broken by original index. Either gets persisted first, both eventually if needed. |

## Trade-offs

- **Greedy largest-first vs. optimal subset**: greedy is O(n log n) and
  good enough. Optimal subset (bin packing) is NP-hard and overkill for
  tens of results.
- **Skip heuristic at `2 * SUMMARY_HEAD_CHARS`**: simple, works. A
  smarter heuristic (e.g., "skip if `len - preview_size < 1KB`") would
  save marginally more disk writes but add complexity for little gain.
- **In-place mutation of `results`**: caller sees the shrinkage. This is
  intended — the caller is about to append `results` to history.

## Compatibility

- No external API change.
- No settings / env var change.
- Existing per-result persistence behavior unchanged.
- Conversation history semantics unchanged (still a list of dicts with
  `type: tool_result` blocks).
