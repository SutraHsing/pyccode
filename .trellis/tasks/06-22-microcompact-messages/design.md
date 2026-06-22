# Design — Microcompact old tool results in history

## Motivation

When an agent reads 10 files in a row to explore a codebase, the first
few reads' full contents keep occupying context long after the agent
moved on. Those old results have three useful properties:

1. **Stale**: the underlying files may have changed on disk, making the
   cached content wrong anyway.
2. **Reproducible**: the agent can re-run the tool to get fresh content
   if it actually needs it later.
3. **Unreferenced**: in most exploration flows, only the most recent
   handful of reads matter for the current step.

Keeping them costs real tokens on every subsequent turn. Clearing them
costs the agent a re-read only if it later decides it needs them — a
trade-off that strongly favors clearing.

## Architecture

Third layer of context management, complementary to the existing two:

| Layer | Trigger | Scope | Effect |
|---|---|---|---|
| `maybePersistLargeToolResult` | per result, >50K | single result | write to disk, replace with ~2.2KB preview |
| `enforceToolResultBudget` | per message, >200K total | one user message | persist largest-first until under budget |
| `microcompactMessages` (new) | per turn, **uncleared** count > 10 | whole history | replace old compactable contents with placeholder |

Each layer runs at a different point in the loop. They do not conflict.

## Trigger Logic: Count Uncleared, Not Total

The trigger counts only **uncleared** `tool_result` blocks — i.e. those
whose `content != OLD_TOOL_RESULT_PLACEHOLDER`. Already-cleared blocks
don't count toward the threshold.

Why this matters (vs. counting all blocks):

| Turn | Total `tool_result` blocks | Uncleared | Trigger? |
|---|---|---|---|
| 11 | 11 | 11 | yes → compact 6, keep 5 |
| 12 | 12 | 6 | **no** (under threshold) |
| 13 | 13 | 7 | **no** |
| ... | ... | ... | ... |
| 16 | 16 | 10 | **no** (exactly at threshold) |
| 17 | 17 | 11 | yes → compact 6, keep 5 |

Counting only uncleared means:

- Compaction fires roughly every `MAX - KEEP_RECENT` turns (every ~5
  turns with defaults), not every turn.
- Each invocation does a meaningful batch of work (clears `MAX - KEEP`
  blocks), not a single-block no-op.
- Prefix cache invalidation happens once per batch instead of once per
  turn. Cache invalidation is the dominant cost of mutating history;
  batching it strictly dominates per-turn mutation.

## Module Constants

Add near the other persistence constants:

```python
MICROCOMPACT_MAX_TOOL_RESULTS = 10     # trigger threshold (uncleared count)
MICROCOMPACT_KEEP_RECENT = 5           # number of recent uncleared results to preserve
COMPACTABLE_TOOLS = frozenset({"bash", "read", "write", "edit", "TodoWrite", "skill"})
OLD_TOOL_RESULT_PLACEHOLDER = "[Old tool result content cleared]"
```

`frozenset` for immutability and O(1) membership check.

## Function Signature

```python
def microcompactMessages(history: list) -> list:
    ...
```

Returns the same `history` reference for convenience (mutation is in
place). Caller may ignore the return value.

## Algorithm

```python
def microcompactMessages(history: list) -> list:
    try:
        # 1. Build tool_use_id -> tool_name index from assistant messages
        tool_use_index = {}
        for msg in history:
            if not isinstance(msg, dict) or msg.get("role") != "assistant":
                continue
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_use_index[block.get("id")] = block.get("name")

        # 2. Collect uncleared compactable tool_result locations
        uncleared_compactable = []   # list of (msg_idx, block_idx) in chronological order
        for msg_idx, msg in enumerate(history):
            if not isinstance(msg, dict):
                continue
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for block_idx, block in enumerate(content):
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                if block.get("content") == OLD_TOOL_RESULT_PLACEHOLDER:
                    continue  # already cleared, skip
                tool_name = tool_use_index.get(block.get("tool_use_id"))
                if tool_name in COMPACTABLE_TOOLS:
                    uncleared_compactable.append((msg_idx, block_idx))

        # 3. Threshold check on UNCLEARED count
        if len(uncleared_compactable) <= MICROCOMPACT_MAX_TOOL_RESULTS:
            return history

        # 4. Compact everything except the most recent KEEP_RECENT uncleared
        to_compact = uncleared_compactable[:-MICROCOMPACT_KEEP_RECENT] \
            if MICROCOMPACT_KEEP_RECENT > 0 else uncleared_compactable
        for msg_idx, block_idx in to_compact:
            history[msg_idx]["content"][block_idx]["content"] = OLD_TOOL_RESULT_PLACEHOLDER

        return history
    except Exception:
        return history
```

## Why a tool_use Index?

`tool_result` blocks carry only `tool_use_id`, not the tool name. To
decide compactability we must recover the name from the matching
`tool_use` block in the preceding assistant message. Building a single
dict once per call is cheaper than re-scanning for each result.

The index is naturally built from assistant messages in a separate first
pass so the lookup is ready when processing tool_results.

## "Recent" Definition

`uncleared_compactable` is built in `enumerate(history)` order, which is
chronological. `uncleared_compactable[-KEEP_RECENT:]` is the most recent
KEEP_RECENT uncleared compactable blocks. `[:-KEEP_RECENT]` is
everything older — these get cleared.

## Failure Modes

| Scenario | Behavior |
|---|---|
| Empty history | Loop does nothing, returns immediately |
| History with no tool_results | `uncleared_compactable` empty, returns |
| Exactly `MAX_TOOL_RESULTS` (10) uncleared | `<=` triggers no-op |
| 11 uncleared, all `run_subagent` | `uncleared_compactable` empty (none compactable); no-op |
| Mismatched `tool_use_id` (no matching `tool_use`) | `tool_name = None`; `None in COMPACTABLE_TOOLS` is False; not added to uncleared list |
| Already-cleared block | Skipped in step 2 (content == placeholder check) |
| Malformed block (not a dict, missing keys) | `isinstance` / `.get` guards prevent crash |
| Exception mid-loop | Top-level try/except returns history unchanged |

## Integration Points

### `chat()` (in the while loop)

Insert before `client.messages.create(...)`:

```python
while True:
    microcompactMessages(history)
    response = client.messages.create(...)
    ...
```

### `handle_subagent()`

Same insertion at the top of the sub-agent's while loop.

## Composition With Existing Layers

```
[turn N starts]
  microcompactMessages(history)             # layer 3: count cap, whole history
  response = client.messages.create(...)
  for each tool_use:
    content = maybePersistLargeToolResult() # layer 1: per-result size cap
    results.append(...)
  results = enforceToolResultBudget(results) # layer 2: per-message size cap
  history.append({role: user, content: results})
[turn N+1 starts]
```

Layer 3 runs first because it's the broadest scope (whole history) and
doesn't depend on the current turn's results.

## Trade-offs

- **Count uncleared, not total**: batches compaction so each trigger
  does meaningful work and cache invalidation events are rarer. Costs
  one extra `if` check per block during the scan; negligible.
- **Count-based, not size-based**: a single huge result that survived
  layer 1 will stay until it ages out of the recent window. Acceptable
  because layer 1 already capped individual sizes.
- **In-place mutation**: caller sees the compaction. Intentional — we
  want the savings to persist across turns.
- **Placeholder is opaque**: agent sees `[Old tool result content
  cleared]` with no info about what was there. Keeps the message simple
  but loses the "what was this?" signal. Acceptable for an
  agent-focused tool; the agent knows the result was compacted and can
  re-run if needed.
- **frozenset for COMPACTABLE_TOOLS**: immutable, O(1) lookup, signals
  "do not mutate at runtime".

## Compatibility

- No external API change.
- No settings / env var change.
- Conversation history semantics: `tool_result.content` may now be the
  placeholder string for old compactable results. The Anthropic API
  accepts arbitrary strings in `tool_result.content`.
