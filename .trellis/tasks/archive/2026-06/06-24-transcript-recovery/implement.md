# Implementation Plan — Move tool-results/ next to transcript under ~/.pyccode/

## Ordered Steps

1. **Add `TOOL_RESULTS_DIR` constant**
   - Place next to other `TRANSCRIPT_*` constants.
   - Value: `TRANSCRIPT_DIR / TRANSCRIPT_CWD / SESSION_ID / "tool-results"`.
   - Validation:
     ```bash
     uv run python -c "import pyccode; print(pyccode.TOOL_RESULTS_DIR)"
     # expect: ~/.pyccode/projects/<sanitized-cwd>/<sessionId>/tool-results
     ```

2. **Update `_persist_tool_result` to use the new path**
   - Replace `result_dir = WORKDIR / SESSION_ID / "tool-results"` with `result_dir = TOOL_RESULTS_DIR`.
   - Everything else (mkdir, write_text, summary, stdout notice) is unchanged because it uses the local `file_path` variable.
   - Validation:
     ```bash
     uv run python -c "
     import pyccode
     summary = pyccode._persist_tool_result('toolu_test', 'X' * 60000)
     assert 'persisted_to:' in summary
     # Extract path
     path_line = [l for l in summary.split(chr(10)) if l.startswith('persisted_to:')][0]
     path = path_line.split(':', 1)[1].strip()
     assert '.pyccode' in path, f'expected ~/.pyccode path, got {path}'
     assert 'tool-results' in path
     # File exists
     import os
     assert os.path.exists(path), f'file not created at {path}'
     # WORKDIR not polluted
     assert not (pyccode.WORKDIR / pyccode.SESSION_ID).exists(), 'WORKDIR should not have session dir'
     print('new path:', path)
     "
     rm -rf ~/.pyccode/projects/
     ```

3. **End-to-end via Layer 1 and Layer 2**
   - Validation:
     ```bash
     uv run python -c "
     import pyccode
     # Layer 1
     pyccode.maybePersistLargeToolResult('toolu_l1', 'A' * 60000)
     # Layer 2 (10 x 30KB = 300KB, triggers budget enforcement)
     rs = [{'type':'tool_result','tool_use_id':f'toolu_l2_{i}','content':'B'*30000} for i in range(10)]
     pyccode.enforceToolResultBudget(rs)
     # Both should land in TOOL_RESULTS_DIR
     files = list(pyccode.TOOL_RESULTS_DIR.iterdir())
     print(f'files in TOOL_RESULTS_DIR: {len(files)}')
     assert len(files) >= 5  # 1 from L1 + at least 4 from L2
     # WORKDIR clean
     assert not (pyccode.WORKDIR / pyccode.SESSION_ID).exists()
     "
     rm -rf ~/.pyccode/projects/
     ```

4. **Failure isolation regression**
   - Validation:
     ```bash
     uv run python -c "
     import pyccode, os
     os.chmod(pyccode.TOOL_RESULTS_DIR.parent, 0o000)
     out = pyccode._persist_tool_result('toolu_fail', 'X' * 60000)
     os.chmod(pyccode.TOOL_RESULTS_DIR.parent, 0o755)
     assert 'persist failed' in out
     assert 'X' * 50000 in out
     print('failure isolation ok')
     "
     rm -rf ~/.pyccode/projects/
     ```

5. **Read-tool recovery sanity**
   - Confirm an agent-style `read` call on the path returns content.
   - Validation:
     ```bash
     uv run python -c "
     import pyccode
     summary = pyccode._persist_tool_result('toolu_read', ('hello world\n' * 10000))
     path = [l.split(':', 1)[1].strip() for l in summary.split(chr(10)) if l.startswith('persisted_to:')][0]
     # Use pyccode's own read handler to simulate agent
     result = pyccode.handle_read({'file_path': path, 'offset': 1, 'limit': 3})
     print(result)
     assert 'hello world' in result
     "
     rm -rf ~/.pyccode/projects/
     ```

6. **Update specs**
   - `.trellis/spec/backend/chat-loop.md`:
     - Update Layer 1 section: replace path examples from `WORKDIR/<sessionId>/...` to `~/.pyccode/projects/<sanitized-cwd>/<sessionId>/tool-results/...`.
     - Update Layer 2 section: same path correction.
     - "Shared rules" → "File layout" line gets the new path.
   - `.trellis/spec/backend/directory-structure.md`:
     - Project Layout diagram: drop the in-project `<sessionId>/` line if mentioned (it isn't, but make sure).
     - Add a note under "Project Layout" or a new "On-Disk Artifacts" subsection listing what pyccode writes outside the project:
       `~/.pyccode/projects/<sanitized-cwd>/<sessionId>.jsonl` (transcript) and
       `~/.pyccode/projects/<sanitized-cwd>/<sessionId>/tool-results/<id>.{txt|json}` (large tool outputs).
   - CLAUDE.md / README.md: update any `WORKDIR/<sessionId>/tool-results/` mention to the new path.

## End-to-End Validation

```bash
# Sanity import
uv run python -c "import pyccode; print('ok')"

# One full simulated turn
uv run python -c "
import pyccode
# Large bash-like output
out = pyccode.maybePersistLargeToolResult('toolu_e2e', 'LOG LINE\n' * 20000)
print(out.split(chr(10))[:4])
# Verify file at new location
import os
assert pyccode.TOOL_RESULTS_DIR.exists()
files = list(pyccode.TOOL_RESULTS_DIR.iterdir())
assert any('toolu_e2e' in f.name for f in files)
# Verify WORKDIR untouched
assert not (pyccode.WORKDIR / pyccode.SESSION_ID).exists()
print('e2e ok')
"
rm -rf ~/.pyccode/projects/
```

## Review Gates

- After step 1: constant prints the expected path.
- After step 2: file lands at new location; WORKDIR untouched.
- After step 3: both layers use the same path; no WORKDIR pollution.
- After step 4: failure path returns legacy truncation.
- After step 6: all docs reference the new path.

## Rollback

Single-file change. `git checkout pyccode.py .trellis/spec/backend/ CLAUDE.md README.md`
restores prior behavior. Files already written to the new location
stay there; the next session after rollback writes to the old
`WORKDIR/<sessionId>/tool-results/` location instead.
