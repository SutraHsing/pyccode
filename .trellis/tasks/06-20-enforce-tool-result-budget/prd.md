# Enforce tool result budget per message

## Goal

Cap the total size of `tool_result` blocks inside a single API-level user
message. When the total exceeds 200KB, persist the largest results to disk
(greedy, largest-first) and replace them with previews until the message
fits the budget.

## Background

`maybePersistLargeToolResult` (pyccode.py:559) handles the per-result case:
any single output over 50K is persisted and replaced with a ~2.2KB summary.
But a message with many medium-sized results (e.g. 10 parallel `bash` calls
each producing 30KB) can still blow past 200KB without tripping the
per-result threshold. The API accepts these large messages today, but they
waste context tokens and slow every subsequent turn.

This task adds a message-level pass that runs after the per-result pass.

## Requirements

### Functional

- New function `enforceToolResultBudget(results: list[dict]) -> list[dict]`:
  - Computes the total `len(content)` across all `tool_result` blocks in
    the list.
  - If total `<= TOOL_RESULT_MESSAGE_BUDGET` (200K chars), returns the
    list unchanged.
  - Otherwise, sorts results by content size descending and persists
    largest-first until total is within budget. Persisted results have
    their `content` replaced with the same preview format used by
    `maybePersistLargeToolResult`.
  - Skips results that are already small enough that persisting would not
    shrink them meaningfully (heuristic: content length `<= 2 * SUMMARY_HEAD_CHARS`).
- Persistence reuses the same file layout, JSON-sniff extension, id
  sanitization, and preview format as `maybePersistLargeToolResult`. No
  new on-disk format.
- Both `chat()` and `handle_subagent()` run `enforceToolResultBudget` on
  the `results` list **after** the per-result `maybePersistLargeToolResult`
  pass and **before** appending the user message to history.
- A short notice is printed to stdout each time `enforceToolResultBudget`
  persists a result, mirroring the existing `[Tool result persisted: ...]`
  line.
- Persistence failures must not break the chat loop. If a single persist
  call fails, skip that result and continue with the next; never raise.

### Non-functional

- Algorithm runs in O(n log n) for the sort; persistence cost is linear
  in the number of results persisted.
- No new external dependencies.
- No new module constants beyond `TOOL_RESULT_MESSAGE_BUDGET`.

## Acceptance Criteria

- [ ] A single tool_result of 250KB triggers `maybePersistLargeToolResult`
      (per-result pass) and produces a ~2.2KB summary; the message total
      after that pass is already under 200KB, so `enforceToolResultBudget`
      does nothing further.
- [ ] A message with 10 × 25KB tool_results (total 250KB, none over the
      per-result 50K threshold) triggers `enforceToolResultBudget`, which
      persists enough of them largest-first to bring the total under 200KB.
- [ ] Persisted results use the same preview format and file path layout
      (`WORKDIR/<sessionId>/tool-results/<id>.{txt|json}`) as
      `maybePersistLargeToolResult`.
- [ ] A message with total exactly 200KB passes through unchanged.
- [ ] Both `chat()` and `handle_subagent()` apply the budget enforcement.
- [ ] A persistence failure (e.g. permission denied on the results dir)
      does not crash the loop; the affected result is left in place and
      the next result is tried.
- [ ] The per-result pass and message-level pass compose without
      double-persisting: results already summarized by
      `maybePersistLargeToolResult` are skipped by
      `enforceToolResultBudget`.

## Out of Scope

- Configurable budget (constant is fine for MVP).
- Compression of persisted content.
- Persisting across messages (this is per-message only).
- Re-tuning `LARGE_TOOL_RESULT_THRESHOLD` or `SUMMARY_HEAD_CHARS`.
