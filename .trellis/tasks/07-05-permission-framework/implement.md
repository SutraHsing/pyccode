# Implementation Plan — Permission framework: allowlist + flag validation

## Ordered Steps

1. **Create package structure**
   - `pyccode/permissions/__init__.py` (empty initially)
   - `pyccode/permissions/engine.py`
   - `pyccode/permissions/allowlist.py`
   - Validation: `uv run python -c "import pyccode.permissions; print('ok')"`

2. **Implement `engine.py`**
   - `CommandConfig` dataclass
   - `_SHELL_OPERATOR_PATTERN`, `_has_shell_operators`
   - `_walk_flags(args, spec)` — flag-walking parser
   - `validate_command(command)` — orchestrates pre-check + shlex + lookup + walk
   - `check_permission(tool_name, tool_input)` — tool-level decision
   - `prompt_user(action)` — y/N reader
   - `CONFIRM_TOOLS = frozenset({"bash", "write", "edit"})`
   - Validation:
     ```bash
     uv run python -c "
     from pyccode.permissions.engine import _has_shell_operators, _walk_flags, CommandConfig
     assert _has_shell_operators('ls; rm')
     assert not _has_shell_operators('ls -la')
     spec = CommandConfig(safe_flags={'-l': 'none', '-n': 'number'})
     assert _walk_flags(['-l'], spec)
     assert _walk_flags(['-n', '5'], spec)
     assert not _walk_flags(['-n', 'abc'], spec)
     assert not _walk_flags(['-x'], spec)
     print('engine ok')
     "
     ```

3. **Implement `allowlist.py`**
   - Import `CommandConfig` from engine
   - Define `READONLY_ALLOWLIST` dict with the 6 commands (ls/cat/pwd/grep/git status/git log)
   - Validation:
     ```bash
     uv run python -c "
     from pyccode.permissions.allowlist import READONLY_ALLOWLIST
     print('commands:', sorted(READONLY_ALLOWLIST.keys()))
     "
     ```

4. **Implement `__init__.py` re-exports**
   - Export `CommandConfig`, `check_permission`, `prompt_user`, `validate_command`
   - Validation: import works

5. **End-to-end `validate_command` tests**
   - Write a test script that exercises all acceptance criteria cases:
     ```bash
     uv run python -c "
     from pyccode.permissions import validate_command, check_permission
     # Allowlist matches
     assert validate_command('ls -la')
     assert validate_command('ls --color=auto')
     assert validate_command('cat -n file.txt')
     assert validate_command('pwd')
     assert validate_command('grep -rn pattern .')
     assert validate_command('grep -i --include=\\\"*.py\\\" pattern')
     assert validate_command('git status -s')
     assert validate_command('git log --oneline -n 5')
     assert validate_command('git log --author=alice')
     # Rejections
     assert not validate_command('ls --evil-flag')
     assert not validate_command('ls; rm -rf /')
     assert not validate_command('grep | wc')
     assert not validate_command('git push --force')  # push not in allowlist
     assert not validate_command('cat file > /etc/passwd')
     assert not validate_command('echo \$(rm)')
     assert not validate_command('rm file')  # rm not in allowlist
     # Tool-level
     assert check_permission('read', {}) == 'allow'
     assert check_permission('write', {}) == 'confirm'
     assert check_permission('bash', {'command': 'ls'}) == 'allow'
     assert check_permission('bash', {'command': 'rm file'}) == 'confirm'
     print('all e2e checks pass')
     "
     ```

6. **Integrate into `handle_bash`**
   - Add import of `check_permission`, `prompt_user`
   - Add early check before subprocess.run
   - Validation:
     ```bash
     # Should NOT prompt (in allowlist)
     uv run python pyccode.py "use bash to run: ls -la pyccode/" 2>&1 | tail -5
     # Should prompt — answer 'n' to deny
     echo 'n' | uv run python pyccode.py "use bash to run: rm /tmp/test_permission" 2>&1 | tail -5
     # Should produce 'Error: Permission denied by user'
     ```

7. **Integrate into `handle_write` and `handle_edit`**
   - Add `prompt_user` call at top of each
   - Validation:
     ```bash
     echo 'n' | uv run python pyccode.py "use write tool to create /tmp/test_perm.txt with content hello" 2>&1 | tail -5
     # Should produce 'Error: Permission denied by user'
     ```

8. **Update specs**
   - New: `.trellis/spec/backend/permissions.md` — describe the model, allowlist commands, fallback semantics
   - Update: `.trellis/spec/backend/directory-structure.md` — add `pyccode/permissions/` to module map
   - Update: `.trellis/spec/backend/error-handling.md` — note `"Error: Permission denied by user"` as a new error category returned by handlers
   - Update: `.trellis/spec/backend/chat-loop.md` — short note that handlers may now refuse to execute
   - Update: `CLAUDE.md` — add permissions module to the module map; add Key Implementation Details bullet about prompt-before-mutate

9. **Final smoke test**
   - `uv run python pyccode.py "reply with: pong"` still works (no permission involved)
   - REPL `ls` works without prompt
   - REPL `rm /tmp/x` prompts and respects y/n
   - Sub-agent inherited (run_subagent running `ls` doesn't prompt)

## End-to-End Validation

```bash
# Sanity import
uv run python -c "import pyccode.permissions; print('ok')"

# Comprehensive validation suite (all should pass)
uv run python -c "
from pyccode.permissions import validate_command, check_permission, prompt_user

# Allowlist
cases_allow = [
    'ls -la', 'ls --color=auto', 'ls -lh pyccode/',
    'cat -n file.txt', 'pwd', 'pwd -L',
    'grep -rn pattern .', 'grep -i --include=*.py pattern',
    'grep -A 3 -B 1 pattern file',
    'git status -s', 'git status --porcelain',
    'git log --oneline -n 5', 'git log --author=alice --since=2024-01-01',
    'git log -p HEAD~3..HEAD',
]
for c in cases_allow:
    assert validate_command(c), f'should allow: {c}'

cases_deny = [
    'ls --evil-flag',
    'ls; rm -rf /',
    'ls && cat /etc/passwd',
    'cat file > /etc/passwd',
    'echo \$(rm -rf /)',
    'grep `whoami` file',
    'git push --force',  # not in allowlist
    'git status; rm file',
    'rm file',  # not in allowlist
    'find . -name x',  # find not in allowlist yet
    '',  # empty
    'ls \"',  # unbalanced quote
]
for c in cases_deny:
    assert not validate_command(c), f'should deny: {c}'

# Tool-level
assert check_permission('read', {}) == 'allow'
assert check_permission('TodoWrite', {}) == 'allow'
assert check_permission('skill', {}) == 'allow'
assert check_permission('run_subagent', {}) == 'allow'
assert check_permission('write', {}) == 'confirm'
assert check_permission('edit', {}) == 'confirm'
assert check_permission('bash', {'command': 'ls'}) == 'allow'
assert check_permission('bash', {'command': 'rm file'}) == 'confirm'

print('all permission checks pass')
"
```

## Review Gates

- After step 2: engine unit-tested in isolation
- After step 5: full validate_command / check_permission behavior matches AC
- After step 7: handlers prompt correctly
- After step 8: specs updated

## Rollback

Single-package addition + 3 handler edits + spec updates. `git checkout
pyccode/tools/bash.py pyccode/tools/file.py .trellis/spec/backend/
CLAUDE.md && rm -rf pyccode/permissions/` restores prior behavior. No
data migration.
