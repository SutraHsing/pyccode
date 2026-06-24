# Implementation Plan — Auto-compact history when context nears limit

## Ordered Steps

1. **Add module constants and prompt template**
   - `AUTOCOMPACT_CONTEXT_WINDOW`, `AUTOCOMPACT_OUTPUT_RESERVE`, `AUTOCOMPACT_BUFFER`, `AUTOCOMPACT_THRESHOLD` (computed), `AUTOCOMPACT_KEEP_RECENT`, `AUTOCOMPACT_MAX_OUTPUT_TOKENS`, `_last_input_tokens = 0`.
   - `AUTOCOMPACT_PROMPT` string (9-section template from design.md).
   - Validation:
     ```bash
     uv run python -c "
     import pyccode
     print('threshold:', pyccode.AUTOCOMPACT_THRESHOLD)  # expect 150000
     print('keep_recent:', pyccode.AUTOCOMPACT_KEEP_RECENT)
     print('prompt length:', len(pyccode.AUTOCOMPACT_PROMPT))
     "
     ```

2. **Add `_callCompactLLM(history) -> str`**
   - Private helper. Calls `client.messages.create` with no tools, the
     compact system prompt, full history + AUTOCOMPACT_PROMPT as final
     user message.
   - Returns the concatenated text blocks.
   - Lets exceptions propagate (caller handles).
   - Validation: hard to unit-test without real API; skip automated
     test, sanity-check at integration step.

3. **Add `_buildCompactSummaryMessage(summary) -> str`**
   - Returns the wrapped summary string with continuation prefix and
     transcript path.
   - Validation:
     ```bash
     uv run python -c "
     import pyccode
     msg = pyccode._buildCompactSummaryMessage('TEST SUMMARY')
     assert 'continued from a previous conversation' in msg
     assert 'TEST SUMMARY' in msg
     assert str(pyccode.TRANSCRIPT_PATH) in msg
     print(msg[:200])
     "
     ```

4. **Add `maybeAutoCompact(history) -> bool`**
   - Top-level function per design.md.
   - Two short-circuit checks (token threshold, history length).
   - try/except around `_callCompactLLM`; on failure or empty summary,
     print yellow stderr notice, return False.
   - On success: `history.clear()`, then `_history_append` boundary
     and summary, then re-extend with recent N.
   - Validation (with mocked LLM):
     ```bash
     uv run python -c "
     import pyccode
     # Mock the compact LLM to avoid real API call
     pyccode._callCompactLLM = lambda h: 'Mocked 9-section summary.'
     # Set token count above threshold
     pyccode._last_input_tokens = pyccode.AUTOCOMPACT_THRESHOLD + 1000
     # Build history with > KEEP_RECENT+2 entries
     history = []
     for i in range(10):
         pyccode._history_append(history, 'user', f'prompt {i}')
         pyccode._history_append(history, 'assistant', f'response {i}')
     original_len = len(history)
     compacted = pyccode.maybeAutoCompact(history)
     assert compacted is True
     # New length: 2 (boundary + summary) + KEEP_RECENT (4)
     assert len(history) == 2 + pyccode.AUTOCOMPACT_KEEP_RECENT
     assert history[0]['content'] == '[compact_boundary]'
     assert 'Mocked 9-section summary.' in history[1]['content']
     print('compact ok, new len:', len(history), 'original:', original_len)
     "
     rm -rf ~/.pyccode/projects/
     ```

5. **Verify short-circuit paths**
   - Validation:
     ```bash
     uv run python -c "
     import pyccode
     pyccode._callCompactLLM = lambda h: 'should not be called'
     # Below threshold
     pyccode._last_input_tokens = 1000
     h = [{'role':'user','content':'x'}] * 20
     assert pyccode.maybeAutoCompact(h) is False
     assert len(h) == 20
     # Above threshold but history too short
     pyccode._last_input_tokens = pyccode.AUTOCOMPACT_THRESHOLD + 1
     h = [{'role':'user','content':'x'}] * 3  # < KEEP_RECENT+2 = 6
     assert pyccode.maybeAutoCompact(h) is False
     assert len(h) == 3
     print('short-circuits ok')
     "
     ```

6. **Verify failure isolation**
   - Validation:
     ```bash
     uv run python -c "
     import pyccode
     pyccode._callCompactLLM = lambda h: (_ for _ in ()).throw(RuntimeError('network down'))
     pyccode._last_input_tokens = pyccode.AUTOCOMPACT_THRESHOLD + 1
     h = []
     for i in range(10):
         pyccode._history_append(h, 'user', f'p{i}')
     original_snapshot = list(h)
     result = pyccode.maybeAutoCompact(h)
     assert result is False
     assert h == original_snapshot  # untouched
     print('failure isolation ok')
     "
     rm -rf ~/.pyccode/projects/
     ```

7. **Wire `_last_input_tokens` tracking into `chat()`**
   - After `response = client.messages.create(...)`, add:
     ```python
     global _last_input_tokens
     if response.usage and response.usage.input_tokens:
         _last_input_tokens = response.usage.input_tokens
     ```
   - Validation: hard to test without API; visual review.

8. **Wire `maybeAutoCompact` call into `chat()`**
   - At top of while loop, after `microcompactMessages(history)`:
     ```python
     maybeAutoCompact(history)
     ```
   - Validation: hard to test without API; visual review.

9. **Update specs**
   - `.trellis/spec/backend/chat-loop.md`:
     - Add Layer 4 section describing auto-compact.
     - Update the loop diagram to show `_last_input_tokens` tracking.
   - `.trellis/spec/backend/directory-structure.md`:
     - Add new constants to the imports+constants item.
     - Add `maybeAutoCompact` / `_callCompactLLM` / `_buildCompactSummaryMessage` to the persistence section.
   - `.trellis/spec/backend/logging-guidelines.md`:
     - Add `[Auto-compact failed: ...]` (stderr) and `[Auto-compact: history reduced to N messages]` (stdout) prefixes.
   - `.trellis/spec/backend/error-handling.md`:
     - Note that auto-compact failures don't crash the loop, just skip.

## End-to-End Validation

```bash
# Sanity import
uv run python -c "import pyccode; print('ok')"

# Full compact flow with mocked LLM (avoids real API cost)
uv run python -c "
import pyccode
pyccode._callCompactLLM = lambda h: '1. Intent: test compact.\n2. Concepts: auto-compact MVP.\n3. Files: pyccode.py\n4-9. ...'
pyccode._last_input_tokens = pyccode.AUTOCOMPACT_THRESHOLD + 5000

# Simulate 8-turn history
history = []
for i in range(8):
    pyccode._history_append(history, 'user', f'turn {i} prompt')
    pyccode._history_append(history, 'assistant', f'turn {i} response')

print(f'pre-compact: {len(history)} messages')
result = pyccode.maybeAutoCompact(history)
print(f'compacted: {result}')
print(f'post-compact: {len(history)} messages')
for i, msg in enumerate(history):
    content_preview = msg['content'][:80].replace(chr(10), ' ')
    print(f'  [{i}] {msg[\"role\"]}: {content_preview}...')

# Verify transcript got boundary + summary
import json
with open(pyccode.TRANSCRIPT_PATH) as f:
    lines = f.readlines()
boundary_lines = [l for l in lines if '[compact_boundary]' in l]
summary_lines = [l for l in lines if 'COMPACT SUMMARY' in l]
print(f'transcript boundary entries: {len(boundary_lines)}')
print(f'transcript summary entries: {len(summary_lines)}')
assert len(boundary_lines) == 1
assert len(summary_lines) == 1
"
rm -rf ~/.pyccode/projects/
```

## Review Gates

- After step 4: mocked-LLM compact produces correct history shape.
- After step 5: short-circuit paths behave correctly.
- After step 6: failure isolation leaves history untouched.
- After step 9: spec updated, full mocked e2e passes.

## Rollback

Single-file change. `git checkout pyccode.py .trellis/spec/backend/`
restores prior behavior. No data migration; transcripts with
`[compact_boundary]` entries from a compacted session just look like
regular user messages to old code.
