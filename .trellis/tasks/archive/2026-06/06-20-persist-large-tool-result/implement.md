# Implementation Plan — Persist large tool results

## Ordered Steps

1. **Add imports and constants** (top of `pyccode.py`)
   - Add `import json`, `import uuid`.
   - Right after `WORKDIR = Path.cwd()`, add:
     - `SESSION_ID = uuid.uuid4().hex`
     - `LARGE_TOOL_RESULT_THRESHOLD = 50000`
     - `SUMMARY_BUDGET = 2048`
   - Validation: `python -c "import pyccode; print(pyccode.SESSION_ID)"` prints a hex string.

2. **Add `maybePersistLargeToolResult(tool_use_id, output)`**
   - Place above `TOOL_HANDLERS = {...}` so it can be referenced by handlers.
   - Implement per `design.md`:
     - Threshold short-circuit.
     - JSON sniff for extension.
     - Sanitize id; build path; mkdir parents; write_text.
     - Build head-only summary; clamp to `SUMMARY_BUDGET`.
     - Print stdout notice.
     - On exception: return legacy truncation + error note.
   - Validation: `python -c "import pyccode; print(len(pyccode.maybePersistLargeToolResult('toolu_test', 'x' * 60000)))"` prints ~2KB.

3. **Wire into `chat()`** (pyccode.py:641-645)
   - Replace `output[:50000]` with `maybePersistLargeToolResult(content.id, output)`.

4. **Wire into `handle_subagent()`** (pyccode.py:534-538)
   - Same replacement.

## End-to-End Validation

After all steps:

```bash
# Sanity: module imports cleanly
python -c "import pyccode; print('ok', pyccode.SESSION_ID[:8])"

# Large text path
python -c "print('hello\n' * 100000)" > /tmp/big.txt
python pyccode.py "use the read tool on /tmp/big.txt and tell me what you got"
# After the run, inspect:
#   ls ./<sessionId>/tool-results/   (filename ends in .txt)
# Dir persists after exit (no auto-cleanup).

# Large JSON path
python -c "import json; print(json.dumps({'k': ['v'] * 50000}))" > /tmp/big.json
python pyccode.py "use the read tool on /tmp/big.json"
# Filename should end in .json

# Subagent path
python pyccode.py "use run_subagent to read /tmp/big.txt and summarize"
# Same session dir; should contain the subagent's persisted file

# Exactly-at-threshold path: 50000 chars must NOT trigger persistence
python -c "print('a' * 50000, end='')" > /tmp/exact.txt
python pyccode.py "use the read tool on /tmp/exact.txt"
# No file should appear under ./<sessionId>/tool-results/
```

## Review Gates

- After step 2: trace by hand with a 60K input to confirm summary length and
  file presence before wiring into the chat loop.
- After step 4: run the end-to-end smoke tests; verify both main and subagent
  paths produce persisted files in the shared session dir.

## Rollback

Single-file change. `git checkout pyccode.py` restores the legacy
`output[:50000]` truncation. No data migration, no schema changes.
