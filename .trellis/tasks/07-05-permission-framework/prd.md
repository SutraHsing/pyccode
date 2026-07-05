# Permission framework: allowlist + flag validation

## Goal

Add a permission layer to pyccode that auto-allows a curated set of
read-only commands and prompts the user (y/N) before running anything
else that mutates state. Bash gets a sub-rule: a built-in read-only
allowlist (with per-flag validation) runs without prompting; everything
else in bash prompts. Write/edit always prompt.

## Background

pyccode currently runs every `bash`/`write`/`edit` tool call without
asking. An agent that misreads a prompt can `rm -rf` the wrong
directory, overwrite a config file, or push to main. We need a
defense-in-depth layer that:

- Auto-allows genuinely read-only commands (ls, cat, grep, etc.) so
  the agent can explore without nagging.
- Prompts the user before anything that could mutate state.
- Is honest about its limits — pattern matching catches accidents, not
  adversarial input. Real sandboxing is a separate concern.

The design follows Claude Code's `COMMAND_ALLOWLIST` model: per-command
`safe_flags` dict mapping each flag to an arg-type (`'none'` /
`'string'` / `'number'`), plus a flag-walking parser that consumes
args correctly. This catches the getopt-long divergences that simpler
substring or shlex-only checks miss.

## Requirements

### Functional

- New package `pyccode/permissions/` with two modules:
  - `engine.py` — `CommandConfig` dataclass, `validate_command`,
    shell-operator pre-check, flag-walking parser, `check_permission`,
    `prompt_user`.
  - `allowlist.py` — `READONLY_ALLOWLIST` dict mapping command name
    (or `git <subcommand>`) to `CommandConfig`.
- `CommandConfig` fields:
  - `safe_flags: dict[str, str]` — flag → arg-type (`'none'` /
    `'string'` / `'number'`). Flags not listed are rejected.
  - `allow_positional: bool = True` — whether non-flag args are
    allowed (False for commands where positionals create side effects,
    e.g., future `git tag`).
- `validate_command(command: str) -> bool` returns True iff:
  - The command has no shell operators (`;`, `|`, `&`, backtick,
    `$(`, or unescaped `>`).
  - `shlex.split` succeeds.
  - `argv[0]` (or `argv[0] + ' ' + argv[1]` for git subcommands) is
    in `READONLY_ALLOWLIST`.
  - Every flag in `argv[1:]` is in the command's `safe_flags`, with
    the correct arg-type consumption (next token for `'string'` /
    `'number'`, no consumption for `'none'`, `=`-attached values for
    long flags, bundle handling for short flags).
  - If `allow_positional` is False, no non-flag args remain after
    flag-walking.
- `check_permission(tool_name: str, tool_input: dict) -> str` returns
  `'allow'` or `'confirm'`:
  - Tools not in `{bash, write, edit}` → `'allow'` (read/TodoWrite/
    skill/run_subagent don't need confirmation).
  - `write` / `edit` → `'confirm'` always (MVP doesn't differentiate
    paths).
  - `bash` → `'allow'` if `validate_command(input['command'])`,
    else `'confirm'`.
- `prompt_user(action: str) -> bool` reads y/N from stdin; returns
  True only on explicit `y`/`yes`; EOFError / KeyboardInterrupt →
  False.
- `handle_bash` calls `check_permission('bash', input)` before
  subprocess.run; if `'confirm'`, calls `prompt_user`; on False,
  returns `"Error: Permission denied by user"` without executing.
- `handle_write` and `handle_edit` follow the same pattern with
  action descriptions like `"Write to <path>"` and `"Edit <path>"`.
- Sub-agent inherits the same checks automatically (uses the same
  handlers).

### Non-functional

- One new package, two new modules (~250 lines total).
- No new external dependencies.
- Permission config is not user-tunable in MVP (constants only).
- No TTY detection — assumes interactive (per design discussion).
- No `dangerous_callback` mechanism (deferred to a future Task 3).
- No `--allow` pre-approval flag (deferred).

## Allowlist Commands (Task 1 scope)

| Command | Notes |
|---|---|
| `ls` | Common display flags: `-l -a -la -lh -R -t -S -h --color` |
| `cat` | No flags needed |
| `pwd` | No flags |
| `grep` | Pattern, output, context flags (full set per Claude Code reference) |
| `git status` | `-s --short -b --branch --porcelain -u --untracked-files` |
| `git log` | `--oneline -n -p --stat --graph --author --since --until --pretty --format` |

`find` is intentionally excluded — it needs dangerous-flag blocking
(`-delete`, `-exec`, `-ok`, etc.) which requires the `dangerous_callback`
mechanism deferred to Task 3.

## Acceptance Criteria

- [ ] `validate_command("ls -la")` returns True.
- [ ] `validate_command("ls --evil-flag")` returns False (unknown flag).
- [ ] `validate_command("ls; rm -rf /")` returns False (shell operator).
- [ ] `validate_command("grep -rn pattern .")` returns True.
- [ ] `validate_command("grep -i --include='*.py' pattern")` returns True.
- [ ] `validate_command("git status -s")` returns True.
- [ ] `validate_command("git push --force")` returns False (push not in allowlist).
- [ ] `validate_command("git log --author=alice")` returns True.
- [ ] `validate_command("cat file > /etc/passwd")` returns False (redirect).
- [ ] `validate_command("echo $(rm -rf /)")` returns False (subshell).
- [ ] `check_permission("read", {...})` returns `'allow'`.
- [ ] `check_permission("write", {...})` returns `'confirm'`.
- [ ] `check_permission("bash", {"command": "ls"})` returns `'allow'`.
- [ ] `check_permission("bash", {"command": "rm file"})` returns `'confirm'`.
- [ ] `handle_bash({"command": "rm file"})` with user answering `n` returns
      `"Error: Permission denied by user"` and does NOT execute the command.
- [ ] `handle_bash({"command": "ls -la"})` runs without prompting.
- [ ] Sub-agent running `ls` doesn't prompt; sub-agent running `rm`
      prompts at the same TTY.

## Out of Scope (deferred)

- `dangerous_callback` mechanism (Task 3) — needed for `find`, `git tag`,
  `git branch`, `date`, `tput`, etc.
- TTY detection and `--allow` pre-approval flags (Task 4 or later) —
  for non-interactive contexts.
- Additional allowlist commands (Task 2): `find`, `sed`, `sort`, `uniq`,
  `date`, `git tag`/`branch` (with callback), `sha256sum`, etc.
- Path-based rules for write/edit (e.g., "writes to /tmp auto-allowed").
- Permission modes beyond `DEFAULT` (e.g., `ACCEPT_EDITS`, `PLAN`).
- Audit logging of confirmed actions.
- Sandboxing (firejail/Docker) — orthogonal concern.
