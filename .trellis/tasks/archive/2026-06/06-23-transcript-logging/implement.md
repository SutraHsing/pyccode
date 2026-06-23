# Implementation Plan — Add transcript JSONL logging for main agent

## Ordered Steps

1. **Add imports and module constants** (pyccode.py top, near other constants)
   - Add `from datetime import datetime, timezone` to imports.
   - Add module constants:
     ```python
     TRANSCRIPT_VERSION = "0.1.0"
     TRANSCRIPT_DIR = Path.home() / ".pyccode" / "projects"
     TRANSCRIPT_CWD = re.sub(r'[^A-Za-z0-9._-]', '-', str(WORKDIR))
     TRANSCRIPT_PATH = TRANSCRIPT_DIR / TRANSCRIPT_CWD / f"{SESSION_ID}.jsonl"
     _transcript_last_uuid = None
     ```
   - Validation:
     ```bash
     uv run python -c "
     import pyccode
     print('version:', pyccode.TRANSCRIPT_VERSION)
     print('path:', pyccode.TRANSCRIPT_PATH)
     print('last_uuid:', pyccode._transcript_last_uuid)
     "
     ```

2. **Add `appendTranscript(role, content)` function**
   - Place near the other persistence helpers (after `microcompactMessages`).
   - Implement per design.md: build entry dict, mkdir parent, open-write-close, update `_transcript_last_uuid`, catch-all on failure with yellow stderr notice.
   - Validation:
     ```bash
     uv run python -c "
     import pyccode, json
     pyccode.appendTranscript('user', 'hello world')
     pyccode.appendTranscript('assistant', 'hi back')
     with open(pyccode.TRANSCRIPT_PATH) as f:
         lines = f.readlines()
     assert len(lines) == 2
     e0 = json.loads(lines[0])
     e1 = json.loads(lines[1])
     assert e0['parentUuid'] is None
     assert e1['parentUuid'] == e0['uuid']
     assert e0['message']['content'] == 'hello world'
     print('chain ok:', e0['uuid'][:8], '->', e1['uuid'][:8])
     "
     # Cleanup
     rm -rf ~/.pyccode/projects/<the sanitized cwd>
     ```

3. **Add `_history_append(history, role, content)` helper**
   - Place right below `appendTranscript`.
   - Body: `history.append({"role": role, "content": content}); appendTranscript(role, content)`.

4. **Migrate `chat()` call sites**
   - Find all five `history.append({"role": ..., "content": ...})` calls in `chat()` and replace with `_history_append(history, role, content)`.
   - Validation: `grep -n 'history\.append' pyccode.py` returns zero matches inside `chat()`.

5. **Do NOT touch `handle_subagent()`**
   - Confirm `messages.append(...)` calls remain unchanged so subagent stays un-transcribed.

6. **Update spec**
   - `.trellis/spec/backend/chat-loop.md`: add a "Transcript Logging" section describing the JSONL side-output, the schema, the integration via `_history_append`, and the explicit non-coverage of subagent.
   - `.trellis/spec/backend/directory-structure.md`: extend the constants list and add `appendTranscript` / `_history_append` to the persistence section.
   - `.trellis/spec/backend/logging-guidelines.md`: add a `[Transcript write failed: ...]` row (to stderr, not stdout).

## End-to-End Validation

```bash
# Sanity import
uv run python -c "import pyccode; print('ok')"

# Non-ASCII content survives
uv run python -c "
import pyccode, json
pyccode.appendTranscript('user', '你好，世界')
with open(pyccode.TRANSCRIPT_PATH) as f:
    line = f.readline()
entry = json.loads(line)
assert entry['message']['content'] == '你好，世界'
print('non-ascii ok:', entry['message']['content'])
"
# Cleanup
rm -rf ~/.pyccide/projects/  # careful — only in dev

# Failure isolation: chmod 000 the dir, write must not crash
uv run python -c "
import pyccode, os, stat
os.chmod(pyccode.TRANSCRIPT_PATH.parent, 0o000)
pyccode.appendTranscript('user', 'this should fail gracefully')
os.chmod(pyccode.TRANSCRIPT_PATH.parent, 0o755)  # restore so cleanup works
print('failure isolation ok')
"
rm -rf ~/.pyccode/projects/

# Full flow: simulate two turns and verify chain
uv run python -c "
import pyccode, json
history = []
pyccode._history_append(history, 'user', 'turn 1 prompt')
pyccode._history_append(history, 'assistant', 'turn 1 response')
pyccode._history_append(history, 'user', 'turn 2 prompt')
with open(pyccode.TRANSCRIPT_PATH) as f:
    entries = [json.loads(line) for line in f]
assert len(entries) == 3
assert entries[0]['parentUuid'] is None
assert entries[1]['parentUuid'] == entries[0]['uuid']
assert entries[2]['parentUuid'] == entries[1]['uuid']
print('3-entry chain ok')
"
rm -rf ~/.pyccode/projects/

# jq validation
uv run python -c "import pyccode; pyccode.appendTranscript('user', 'x')"
jq -c . <(cat ~/.pyccode/projects/*/$(python -c 'import pyccode; print(pyccode.SESSION_ID)').jsonl)
rm -rf ~/.pyccode/projects/
```

## Review Gates

- After step 2: chain forms correctly across two writes.
- After step 4: zero `history.append` calls inside `chat()`; all five migrated.
- After step 6: spec updated, end-to-end smoke tests pass.

## Rollback

Single-file change plus `~/.pyccode/` artifacts. `git checkout pyccode.py
.trellis/spec/backend/` restores prior behavior; `rm -rf ~/.pyccode/`
cleans up generated files. No data migration.
