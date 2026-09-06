# Implementation Plan — Transcript v2 via internal MessageAppend hook

## Ordered Steps

1. **engine.py: MESSAGE_APPEND + internal registry + dispatch split**
   - Validation:
     ```bash
     uv run python -c "
     from pyccode.hooks.engine import HookType, register_internal_hook, run_hooks
     assert HookType.MESSAGE_APPEND.value == 'MessageAppend'
     calls = []
     register_internal_hook(HookType.MESSAGE_APPEND, lambda p: calls.append(p['role']))
     def boom(p): raise RuntimeError('x')
     register_internal_hook(HookType.MESSAGE_APPEND, boom)
     run_hooks(HookType.MESSAGE_APPEND, {'role': 'user'})
     assert calls == ['user']   # boom isolated, no raise
     print('internal registry ok')
     "
     ```

2. **settings.py: EXTERNAL_EVENTS gate**
   - Validation:
     ```bash
     uv run python -c "
     import json
     from pyccode.hooks.settings import load_settings, SETTINGS_PATH
     SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
     SETTINGS_PATH.write_text(json.dumps({'hooks': {
         'MessageAppend': [{'command': 'echo evil'}],
         'PostToolUse': [{'command': 'echo ok'}],
     }}))
     s = load_settings(force_reload=True)
     assert 'MessageAppend' not in s.hooks      # gated out
     assert len(s.hooks.get('PostToolUse', [])) == 1
     print('external gate ok')
     SETTINGS_PATH.unlink()
     "
     ```

3. **transcript.py: appendTranscript(+usage, +gitBranch), _read_git_branch,
   history_append fires MessageAppend, hook + registration**
   - Validation:
     ```bash
     uv run python -c "
     import json
     from pyccode.context.transcript import history_append
     from pyccode.config import TRANSCRIPT_PATH
     h = []
     history_append(h, 'user', 'q1')
     history_append(h, 'assistant', [{'type': 'text', 'text': 'a1'}],
                    usage={'input_tokens': 10, 'output_tokens': 3})
     entries = [json.loads(l) for l in TRANSCRIPT_PATH.read_text().strip().splitlines()]
     assert len(entries) == 2
     assert all(e['gitBranch'] for e in entries)
     assert entries[1]['message']['usage'] == {'input_tokens': 10, 'output_tokens': 3}
     assert entries[1]['parentUuid'] == entries[0]['uuid']
     assert 'usage' not in entries[0]['message']
     print('transcript v2 fields + chain ok')
     "
     # rm the test session file afterwards
     ```

4. **chat.py: pass usage on assistant turns**
   - Validation:
     ```bash
     uv run python pyccode.py "reply with exactly: pong"
     LATEST=$(ls -t ~/.pyccode/projects/-Users-sutra-PycharmProjects-pyccode/*.jsonl | head -1)
     python3 -c "
     import json
     e = [json.loads(l) for l in open('$LATEST')]
     assert e[-1]['type'] == 'assistant'
     assert e[-1]['message'].get('usage', {}).get('output_tokens', 0) > 0
     assert e[-1]['gitBranch']
     print('real-run usage + gitBranch ok')
     "
     ```

5. **Regression: compact path + REPL chain + external PostToolUse**
   - Compact (mock LLM):
     ```bash
     uv run python -c "
     import json
     from pyccode.context.layers import maybeAutoCompact
     from pyccode.context.transcript import history_append
     import pyccode.context.layers as L
     from pyccode.config import TRANSCRIPT_PATH
     L._callCompactLLM = lambda h: 's'
     L.AUTOCOMPACT_THRESHOLD = 10
     h = [history_append(h, 'user', f'p{i}') or history_append(h, 'assistant', f'r{i}') for i in range(8) for h in [h]][-1] if False else None
     h = []
     for i in range(8):
         history_append(h, 'user', f'p{i}')
         history_append(h, 'assistant', f'r{i}')
     assert maybeAutoCompact(h, 99999) is True
     kinds = [json.loads(l)['message']['content'][:20] for l in TRANSCRIPT_PATH.read_text().strip().splitlines()]
     assert any('[compact_boundary]' in k for k in kinds)
     print('compact entries ok')
     "
     ```
   - REPL chain:
     ```bash
     uv run python - <<'EOF'
     from pyccode.chat import chat
     import json
     from pyccode.config import TRANSCRIPT_PATH
     h = []
     chat("reply: one", h)
     chat("reply: two", h)
     e = [json.loads(l) for l in TRANSCRIPT_PATH.read_text().strip().splitlines()]
     for a, b in zip(e, e[1:]):
         assert b['parentUuid'] == a['uuid']
     print('REPL chain ok:', len(e), 'entries')
     EOF
     ```
   - External PostToolUse marker (existing pattern from previous task).

6. **Spec + docs**
   - `hooks.md`: internal hook section (registry, dispatch order,
     internal-only MessageAppend, external gate), division of labor
     transcript-vs-audit, Stop recorded in roadmap with use cases.
   - `chat-loop.md`: transcript timing unchanged (incremental) but routed via
     MessageAppend hook; assistant entries carry usage.
   - `directory-structure.md` / `CLAUDE.md`: bullets updated.

## End-to-End Validation

```bash
uv run python pyccode.py "reply with: pong"
# → entries have gitBranch + message.usage; chain intact; external hooks unaffected
```

## Review Gates

- After step 3: synthetic entries carry both new fields, chain intact.
- After step 4: real API run produces usage from response.
- After step 5: compact + REPL + external regressions all green.

## Rollback

`git checkout pyccode/ .trellis/spec/ CLAUDE.md` — restores v1 inline
transcript. Schema changes are additive only.
