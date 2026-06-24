# Design — Auto-compact history when context nears limit

## Architecture

Fourth layer of context management. Runs once per turn before the API
call, same insertion point as `microcompactMessages`.

```
[turn N starts]
  microcompactMessages(history)         # layer 3: count cap
  maybeAutoCompact(history)             # layer 4 (new): token cap
  response = client.messages.create(...)
  _last_input_tokens = response.usage.input_tokens   # NEW
  for each tool_use:
    maybePersistLargeToolResult(...)    # layer 1: per-result size
  enforceToolResultBudget(results)      # layer 2: per-message size
  _history_append(history, "user", results)
[turn N+1 starts]
```

Layer 4 uses **real token data** from the previous response — no
estimation, no tokenizer dependency.

## Module Constants

```python
AUTOCOMPACT_CONTEXT_WINDOW = 200_000       # Sonnet-class default
AUTOCOMPACT_OUTPUT_RESERVE = 20_000        # reserved for model output
AUTOCOMPACT_BUFFER = 30_000                # safety margin below the hard limit
AUTOCOMPACT_THRESHOLD = AUTOCOMPACT_CONTEXT_WINDOW - AUTOCOMPACT_OUTPUT_RESERVE - AUTOCOMPACT_BUFFER
                                            # = 150_000
AUTOCOMPACT_KEEP_RECENT = 4                # messages to preserve after compact
AUTOCOMPACT_MAX_OUTPUT_TOKENS = 16_384     # cap for summary LLM call

_last_input_tokens = 0                     # updated by chat() after each response
```

`AUTOCOMPACT_THRESHOLD` is computed, not literal, so tuning any of the
three inputs automatically updates the trigger.

## Function Signatures

### `maybeAutoCompact(history: list) -> bool`

Top-level entry point. Returns `True` if a compact happened.

```python
def maybeAutoCompact(history: list) -> bool:
    if _last_input_tokens <= AUTOCOMPACT_THRESHOLD:
        return False
    if len(history) < AUTOCOMPACT_KEEP_RECENT + 2:
        return False

    try:
        summary = _callCompactLLM(history)
    except Exception as e:
        print(f"\033[33m[Auto-compact failed: {e}]\033[0m", file=sys.stderr)
        return False

    if not summary or not summary.strip():
        print("\033[33m[Auto-compact failed: empty summary]\033[0m", file=sys.stderr)
        return False

    recent = history[-AUTOCOMPACT_KEEP_RECENT:]
    history.clear()
    _history_append(history, "user", "[compact_boundary]")
    _history_append(history, "user", _buildCompactSummaryMessage(summary))
    for msg in recent:
        history.append(msg)  # already in transcript; don't re-append

    print(f"\033[33m[Auto-compact: history reduced to {len(history)} messages]\033[0m")
    return True
```

Key decisions:

- **Two-tier short-circuit**: token check first (cheap), history length
  second (also cheap). Skip work entirely if either fails.
- **try/except around the LLM call**: any failure (network, 5xx, JSON
  parse, SDK exception) is caught and reported via stderr. History is
  untouched.
- **Empty-summary check**: defensive. If the LLM returns nothing
  usable, treat as failure.
- **`history.clear()` then re-populate**: in-place mutation. Callers
  see the shrinkage.
- **`recent` is references, not copies**: the same dict objects that
  were in history go back. They're not re-appended to transcript
  because they're already there.
- **Boundary and summary go through `_history_append`**: ensures they
  land in both history and transcript consistently with every other
  message.

### `_callCompactLLM(history: list) -> str`

Private helper. Makes the summarization API call.

```python
def _callCompactLLM(history: list) -> str:
    response = client.messages.create(
        model=os.environ.get("MODEL_NAME", "claude-sonnet-4-5-20250929"),
        max_tokens=AUTOCOMPACT_MAX_OUTPUT_TOKENS,
        system="You are a helpful AI assistant tasked with summarizing conversations.",
        messages=history + [{"role": "user", "content": AUTOCOMPACT_PROMPT}],
    )
    return "".join(c.text for c in response.content if c.type == "text")
```

Why no `tools=[]`?

The Anthropic SDK treats omitting `tools` and passing `tools=[]`
equivalently — both mean "no tools available". Omitting is cleaner.

Why `history + [prompt]` instead of injecting the prompt into the
system?

The summary instructions are conversation-specific ("summarize the
above"). Putting them in a final user message keeps the system prompt
stable and lets the model see the prompt in conversation context.

### `_buildCompactSummaryMessage(summary: str) -> str`

Wraps the LLM-generated summary with the continuation prefix.

```python
def _buildCompactSummaryMessage(summary: str) -> str:
    return (
        "This session is being continued from a previous conversation "
        "that ran out of context. A compact summary follows. Do not "
        "recap or ask the user what to do next — continue the work "
        "from where it left off.\n\n"
        f"If you need specific details from before compaction (exact "
        f"code snippets, error messages, content you generated), read "
        f"the full transcript at: {TRANSCRIPT_PATH}\n\n"
        "--- COMPACT SUMMARY ---\n"
        f"{summary.strip()}\n"
        "--- END SUMMARY ---"
    )
```

## Summary Prompt Template

`AUTOCOMPACT_PROMPT` is a module-level string. 9 sections adapted from
Claude Code's design:

```python
AUTOCOMPACT_PROMPT = """\
Summarize the conversation above so a fresh agent can continue the
work without re-reading the full transcript. Respond with TEXT ONLY -
do not call any tools.

Cover these 9 sections, in order, each as a short paragraph or bullet
list:

1. Primary Request and Intent
   What the user originally asked for, plus any clarifications or
   scope changes that came up during the conversation.

2. Key Technical Concepts
   Domain knowledge, project conventions, constraints, or definitions
   the agent needs to do the work. Name names (libraries, tools,
   patterns).

3. Files and Code Sections
   Specific files touched, read, or modified. Include function
   signatures, key snippets, and line numbers where relevant.

4. Errors and Fixes
   Bugs hit, root causes identified, and how each was resolved. Quote
   exact error text where useful.

5. Problem Solving
   Decisions made, alternatives considered, trade-offs accepted.
   Include any rejected approaches and why.

6. All User Messages
   Verbatim or near-verbatim list of every user prompt, clarification,
   or piece of feedback. Number them.

7. Pending Tasks
   What's left to do. Be specific - link to acceptance criteria,
   checklists, or open PR comments where applicable.

8. Current Work
   What was being done when context ran out. Name the file being
   edited, the test being run, the question being answered.

9. Optional Next Step
   The single most immediate action to take. Concrete, not aspirational.

Be specific and dense. File paths, function names, exact error strings
- include them. A vague summary forces the next agent to re-read the
transcript, which defeats the point.
"""
```

This is more structured than Claude Code's prompt (which interleaves
the sections differently) but covers the same ground.

## Integration in `chat()`

Two surgical changes inside the existing while loop:

1. Track tokens after each API response:

   ```python
   response = client.messages.create(...)
   global _last_input_tokens
   if response.usage and response.usage.input_tokens:
       _last_input_tokens = response.usage.input_tokens
   ```

2. Call `maybeAutoCompact` at the top of the loop, after
   `microcompactMessages`:

   ```python
   while True:
       microcompactMessages(history)
       maybeAutoCompact(history)
       response = client.messages.create(...)
       ...
   ```

Order matters: `microcompactMessages` runs first (cheap, count-based),
then `maybeAutoCompact` (expensive, LLM call) if still needed.

`handle_subagent()` gets neither — it has its own loop and is
intentionally not auto-compacted in MVP.

## Token Source

`response.usage.input_tokens` is the actual token count the API
computed for the request we just sent. Using it as the trigger metric
means:

- **No estimation error**: the threshold check uses real data.
- **No new dependencies**: no tiktoken, no API call to
  `count_tokens`.
- **Lag of one turn**: we react to the last turn's size, not predict
  the next. If the last turn was 149K tokens, we don't compact; the
  next turn might push to 165K and fail. Acceptable for MVP given
  Layer 1-3 already control tool outputs.

The lag is the main trade-off. Claude Code has predictive auto-compact
to close this gap; deferred here.

## Failure Modes

| Scenario | Behavior |
|---|---|
| First turn (`_last_input_tokens = 0`) | Threshold check fails; no compact. |
| Token count below threshold | Early return, no work. |
| History too short | Early return, no work. |
| LLM call raises (network, 5xx, auth) | Caught, yellow stderr notice, history untouched, returns `False`. |
| LLM returns empty text | Treated as failure, same handling. |
| LLM returns text with tool_use blocks | `c.type == "text"` filter drops non-text blocks; summary is whatever text came back. Tools aren't passed to the call so this shouldn't happen. |
| Compact succeeds but next turn's `_last_input_tokens` is still > threshold | Next turn triggers another compact. Eventual consistency. |

## Trade-offs

- **Reactive, not predictive**: simple, real data, one-turn lag. MVP
  trade-off; predictive can be added later as a separate check.
- **No failure counter**: if compact keeps failing, we keep trying
  every turn. Cost: one extra LLM call attempt per turn until it
  succeeds or tokens drop. Claude Code's 3-strike disable is
  defensive but adds state; defer.
- **Whole-history summary**: the compact LLM call sends the entire
  history as input. If history is 180K tokens, the summary call
  itself consumes 180K input tokens. That's the cost of doing the
  compact; the savings come from all subsequent turns.
- **`_last_input_tokens` is module-global**: not thread-safe. pyccode
  is single-threaded; fine.
- **No skill re-injection**: the first user message's skill metadata
  is lost after compact. Skills are still available via the `skill`
  tool (system prompt unchanged), so the model can re-load on demand.

## Compatibility

- No external API change.
- No settings / env var change.
- Conversation history semantics: after a compact, history has a
  different shape (boundary + summary + recent). The Anthropic API
  accepts arbitrary user/assistant alternation, so this is fine.
- Transcript: two new entries per compact (boundary, summary). Both
  are regular user-role entries with recognizable content prefixes.
- Future resume: detect `[compact_boundary]` in transcript to know
  where compacts happened; the summary message's prefix gives the
  transcript path for full recovery.
