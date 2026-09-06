# Implementation Plan — PostToolUse subprocess hook framework

## Ordered Steps

1. **Create `pyccode/hooks/` package skeleton**
   - `mkdir pyccode/hooks`
   - Empty `__init__.py` for now
   - Validation: `uv run python -c "import pyccode.hooks; print('ok')"`

2. **Implement `pyccode/hooks/engine.py`**
   - `HookType` enum (POST_TOOL_USE only)
   - `HookConfig` dataclass
   - `HookOutcome` dataclass
   - `build_post_tool_use_payload(...)` — assembles the 12-field dict
   - `run_hook(config, payload)` — subprocess wrapper, never raises
   - `run_hooks(event, payload)` — dispatcher, prints stderr on failure
   - Validation:
     ```bash
     uv run python -c "
     from pyccode.hooks.engine import run_hook, HookConfig
     # Trivial hook: cat stdin back to stdout, exit 0
     out = run_hook(HookConfig(command='cat'), {'test': 'payload'})
     assert out.exit_code == 0
     assert 'test' in out.stdout
     print('run_hook ok')

     # Failing hook
     out = run_hook(HookConfig(command='exit 42'), {'x': 1})
     assert out.exit_code == 42
     print('failure capture ok')

     # Timeout
     out = run_hook(HookConfig(command='sleep 10', timeout_ms=100), {'x': 1})
     assert out.timed_out
     print('timeout ok')
     "
     ```

3. **Implement `pyccode/hooks/settings.py`**
   - `SETTINGS_PATH = Path.home() / '.pyccode' / 'settings.json'`
   - `SettingsSchema` dataclass
   - `load_settings(force_reload=False)` with module-level cache
   - Validation:
     ```bash
     uv run python -c "
     from pyccode.hooks.settings import load_settings
     # Missing file
     s = load_settings(force_reload=True)
     assert s.hooks == {}
     # With file
     import json
     from pyccode.hooks.settings import SETTINGS_PATH
     SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
     SETTINGS_PATH.write_text(json.dumps({
         'hooks': {'PostToolUse': [{'command': 'echo hi', 'timeout_ms': 1000}]}
     }))
     s = load_settings(force_reload=True)
     assert len(s.hooks.get('PostToolUse', [])) == 1
     assert s.hooks['PostToolUse'][0].command == 'echo hi'
     print('settings ok')
     # Cleanup
     SETTINGS_PATH.unlink()
     "
     ```

4. **Wire up `pyccode/hooks/__init__.py`**
   - Re-export public API
   - Validation: `uv run python -c "from pyccode.hooks import run_hooks, HookType, build_post_tool_use_payload; print('ok')"`

5. **Integrate into `chat()` main loop** (`pyccode/chat.py`)
   - Find the existing tool-execution loop
   - Insert `run_hooks(...)` call **after** `output = handler(...)`,
     **before** `results.append(...)`
   - Use `agent_id="main"`
   - Validation:
     ```bash
     # Write a test hook that creates a marker file
     mkdir -p ~/.pyccode
     cat > ~/.pyccode/settings.json <<'EOF'
     {
       "hooks": {
         "PostToolUse": [
           {"command": "python3 -c \"import sys, json, pathlib; p = json.loads(sys.stdin.read()); pathlib.Path('/tmp/pyccode_hook_marker').write_text(p['tool_name'] + ':' + p['agent_id'])\"", "timeout_ms": 5000}
         ]
       }
     }
     EOF
     rm -f /tmp/pyccode_hook_marker
     uv run python pyccode.py "use bash to run: echo hello"
     cat /tmp/pyccode_hook_marker
     # Expected: bash:main
     rm /tmp/pyccode_hook_marker
     rm ~/.pyccode/settings.json
     ```

6. **Integrate into `handle_subagent()`** (same file `pyccode/chat.py`)
   - Same insertion in the subagent's tool-execution loop
   - Use `agent_id="subagent"`
   - Validation:
     ```bash
     # Same setup as above, then:
     uv run python pyccode.py "use run_subagent to run: echo from-sub"
     cat /tmp/pyccode_hook_marker
     # Expected: bash:subagent (subagent ran the bash tool)
     rm /tmp/pyccode_hook_marker
     rm ~/.pyccode/settings.json
     ```

7. **Write example hook script** in `examples/hooks/audit.py`
   - Reads stdin JSON, appends summary line to `~/.pyccode/audit.jsonl`
   - Documents the payload schema in its docstring
   - Validation:
     ```bash
     mkdir -p ~/.pyccode
     cat > ~/.pyccode/settings.json <<'EOF'
     {"hooks": {"PostToolUse": [{"command": "python3 examples/hooks/audit.py", "timeout_ms": 5000}]}}
     EOF
     rm -f ~/.pyccode/audit.jsonl
     uv run python pyccode.py "use bash to run: ls pyccode/"
     cat ~/.pyccode/audit.jsonl | jq .
     # Verify entries exist with session_id, tool_name='bash', agent_id='main'
     rm ~/.pyccode/settings.json
     rm ~/.pyccode/audit.jsonl
     ```

8. **Write `.trellis/spec/backend/hooks.md`**
   - Document the 5 use cases that motivated the framework
   - Payload schema (12 fields, table form)
   - Subprocess contract (stdin/stdout/stderr/exit code)
   - Failure isolation guarantees
   - Future hook types roadmap (PreToolUse, UserPromptSubmit, Stop)
   - 3 intentional divergences from Claude Code

9. **Update CLAUDE.md / directory-structure.md / chat-loop.md**
   - Add `pyccode/hooks/` to module map
   - Add PostToolUse firing point to chat-loop.md
   - Add `[Hook '<cmd>' failed: ...]` to logging-guidelines.md prefix table

10. **End-to-end failure-isolation test**
    - Configure a hook that crashes (e.g. `command: "python3 -c 'import sys; sys.exit(1)'"`)
    - Verify chat loop continues, stderr has `[Hook ... failed: exit 1]`
    - Configure a hook that times out (`command: "sleep 100"`, `timeout_ms: 200`)
    - Verify chat loop continues, stderr has `[Hook ... timed out after 200ms]`

## End-to-End Validation

After all steps:

```bash
# Sanity import
uv run python -c "import pyccode; from pyccode.hooks import run_hooks; print('ok')"

# No settings.json → no hooks fire
uv run python pyccode.py "reply with: pong"
# Expected: pong (no extra output)

# With audit hook
mkdir -p ~/.pyccode
cat > ~/.pyccode/settings.json <<'EOF'
{"hooks": {"PostToolUse": [{"command": "python3 examples/hooks/audit.py", "timeout_ms": 5000}]}}
EOF
rm -f ~/.pyccode/audit.jsonl
uv run python pyccode.py "use bash to run: ls pyccode/"
echo '--- audit log ---'
cat ~/.pyccode/audit.jsonl | jq .
rm ~/.pyccode/settings.json
rm ~/.pyccode/audit.jsonl
```

## Review Gates

- After step 2: hook executor works in isolation (success / failure / timeout)
- After step 3: settings loader handles missing/malformed file gracefully
- After step 5: main agent chat fires hook with correct payload
- After step 6: subagent also fires, `agent_id` correctly distinguishes
- After step 7: real audit log file generated, payload schema verified end-to-end
- After step 10: failure isolation proven (chat survives bad hooks)

## Rollback

Multi-file change but additive. `git checkout pyccode/ pyccode/chat.py
.trellis/spec/backend/ CLAUDE.md examples/` restores prior behavior.
Removing `~/.pyccode/settings.json` is sufficient to disable at runtime
without code rollback.
