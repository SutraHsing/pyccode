# Microcompact old tool results in history

## Goal

Cap the total number of `tool_result` blocks accumulated in conversation
history. When the count exceeds a threshold (default 10), replace the
oldest compactable tool_result contents with a placeholder, keeping only
the most recent few (default 5) intact.

## Background

`enforceToolResultBudget` caps the **size** of a single user message.
But after many turns, the conversation accumulates dozens of tool_result
blocks even if each message was small. Long histories inflate every API
call's token cost and slow every subsequent turn.

Typical pattern: an agent reads 10 files in a row to explore a codebase.
The first 5 reads' full contents are still sitting in context, even
though:

- The agent has long since moved past them and no longer references them.
- The underlying files may have changed on disk, making the cached
  content stale anyway.
- The information is **reproducible** — the agent can re-run `read` if
  it actually needs the content again.

Clearing these old, reproducible results has minimal side effects:
losing them costs the agent a re-read only if it later decides it needs
them. Keeping them costs real tokens on every subsequent turn.

This feature is the count-based complement to the existing size-based
layers: it doesn't care how big each result is, only how many have piled
up.

## Requirements

### Functional

- New function `microcompactMessages(history: list) -> list`:
  - Counts **uncleared** `tool_result` blocks across every message in
    `history`. A block is "uncleared" iff its `content` is not equal to
    `OLD_TOOL_RESULT_PLACEHOLDER`.
  - If uncleared count `<= MICROCOMPACT_MAX_TOOL_RESULTS` (default 10),
    returns unchanged.
  - Otherwise, leaves the most recent `MICROCOMPACT_KEEP_RECENT` (default
    5) **uncleared compactable** `tool_result` blocks untouched and
    replaces the `content` of older **uncleared compactable** ones with
    `OLD_TOOL_RESULT_PLACEHOLDER` (`"[Old tool result content cleared]"`).
  - Non-compactable tool_results are never touched, even when old.
  - Already-cleared blocks are never re-touched (idempotent).
- A tool_result is compactable iff the tool that produced it is in
  `COMPACTABLE_TOOLS`. The tool name is recovered by scanning assistant
  messages for the matching `tool_use` block (by `tool_use_id`).
- `COMPACTABLE_TOOLS` = `frozenset({"bash", "read", "write", "edit", "TodoWrite", "skill"})`.
  Notably **excludes** `run_subagent` — sub-agent outputs are one-shot
  and cannot be reproduced.
- Runs once per turn, **before** the API call in both `chat()` and
  `handle_subagent()`. It mutates history in place; no return value
  needs to be captured by the caller (the same list reference is
  returned for convenience).
- Never raises. Any internal error (malformed block, missing key) is
  swallowed so the chat loop is unaffected.

### Non-functional

- O(n) in history length per call — single pass to build the
  `tool_use_id → name` index, single pass to collect tool_result
  locations.
- No new external dependencies.
- No on-disk state.

## Acceptance Criteria

- [ ] A history with 10 or fewer **uncleared** compactable `tool_result`
      blocks is returned unchanged.
- [ ] A history with 11+ uncleared compactable blocks has all but the
      most recent 5 replaced with `"[Old tool result content cleared]"`.
- [ ] After a compaction pass leaves 5 uncleared compactable blocks,
      adding up to 5 more does **not** re-trigger compaction (because
      uncleared count stays `<= MAX`). The next trigger happens only
      when uncleared count exceeds MAX again.
- [ ] Already-cleared blocks (`content == OLD_TOOL_RESULT_PLACEHOLDER`)
      are not modified again by subsequent calls (idempotent on stable
      history).
- [ ] `tool_result` blocks produced by `run_subagent` are never
      compacted, regardless of age or count.
- [ ] `tool_result` blocks whose `tool_use_id` cannot be matched to any
      `tool_use` block (should not happen in practice) are treated as
      non-compactable and left alone.
- [ ] Both `chat()` and `handle_subagent()` invoke `microcompactMessages`
      before each API call.
- [ ] Malformed history entries (missing keys, wrong types) do not
      crash the chat loop.

## Out of Scope

- Configurable thresholds (constants are fine for MVP).
- Compacting `tool_use` blocks themselves — only `tool_result` contents.
- Compacting assistant text or other content blocks.
- Cross-session compaction (only affects the in-memory history of the
  current process).
- Re-tuning `enforceToolResultBudget` or `maybePersistLargeToolResult`.
