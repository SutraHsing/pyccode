# Permissions

> pyccode prompts the user (y/N) before any tool call that mutates state. Read-only commands in the allowlist run without prompting.

---

## Model

Three tiers (today: allow + confirm; future: deny):

1. **Allow**: `ALLOWED_TOOLS = {read, TodoWrite, skill, run_subagent}` auto-pass without prompting. Plus, for `bash`, any command matching `READONLY_ALLOWLIST` (Task 1: ls/cat/pwd/grep/git status/git log) via flag-walking validation.
2. **Confirm (default)**: everything else prompts the user with y/N. This includes `bash` commands not in the allowlist, `write`, `edit`, and any future tool that isn't explicitly added to `ALLOWED_TOOLS`. **Default-confirm** means new tools / commands get a prompt until explicitly listed — visible, easy to fix — rather than silently auto-running.
3. **Deny (future)**: a configurable hard-deny list (`DENY_LIST`) for things that should never run even with explicit user consent — fork bombs, raw disk writes, etc. Reserved for a later task; not implemented yet.

Decision function: `check_permission(tool_name, tool_input) -> 'allow' | 'confirm'`. Handlers call this before doing work; on `'confirm'` they call `prompt_user` and either proceed or return `"Error: Permission denied by user"`.

---

## Allowlist Validation

`validate_command(command: str) -> bool` returns True iff:

1. Command has no shell operators (`;`, `|`, `&`, backtick, `$(`, or unescaped `>`).
2. `shlex.split` succeeds.
3. `argv[0]` (or `argv[0] + ' ' + argv[1]` for git subcommands) is in `READONLY_ALLOWLIST`.
4. Every flag in `argv[1:]` is in the command's `safe_flags`, with correct arg-type consumption.
5. If `allow_positional=False`, no positional args remain.

Failure on any step → fall through to confirm.

### Arg Types

`CommandConfig.safe_flags` maps each allowed flag to one of:

- `'none'` — boolean flag, no arg consumed.
- `'string'` — consumes next token as required string arg.
- `'number'` — consumes next token as required numeric arg.

Flags not listed are rejected. This catches getopt-long divergences (e.g., GNU `xargs -i` semantics) by enforcing that validator and tool agree on arg consumption.

### Flag-Walking Parser

`_walk_flags(args, spec)` handles:

- `--flag=value` (attached long flag)
- `--flag value` (detached long flag for `'string'` / `'number'`)
- `-f` (short flag, `'none'`)
- `-fvalue` (short flag with attached value)
- `-abc` (short flag bundle — all `'none'`, or last char takes arg)
- `--` (end of options; rest are positional)

---

## Allowlisted Commands (Task 1 Scope)

| Command | Notes |
|---|---|
| `ls` | Display flags: `-l -a -la -lh -R -t -S -h -r -F -1 --color` |
| `cat` | `-n -b -s -A -E -T -v` |
| `pwd` | `-L -P` |
| `grep` | Full read-only flag set: pattern, match, output, context, file/dir selection |
| `git status` | `-s --short -b --branch --porcelain --long -v --verbose -u --untracked-files --ignored --ignore-submodules --column --ahead-behind --renames --find-renames -M` |
| `git log` | `--oneline -p --stat --graph -n --skip --author --grep --since --until --pretty --format --first-parent --no-merges --reverse --all -S -G --date --name-only --name-status` |

**Not yet in allowlist** (need future `dangerous_callback` mechanism):

- `find` — needs to block `-delete`, `-exec`, `-execdir`, `-ok`, `-okdir`, `-fprint*`, `-fls`
- `git tag` — positional arg creates ref
- `git branch` — positional arg creates branch
- `date` — positional arg sets system time
- `tput` — positional capability may run iprog

These commands fall through to confirm. User decides per call.

---

## Handler Integration

### `handle_bash`

```python
if check_permission("bash", input) == "confirm":
    if not prompt_user(f"Run bash: {command}"):
        return "Error: Permission denied by user"
```

Print the `$ <command>` line **after** the permission check passes (don't echo commands that were denied).

### `handle_write` / `handle_edit`

Always prompt (no path-based rules in MVP):

```python
if not prompt_user(f"Write to {file_path}"):  # or "Edit {file_path}"
    return "Error: Permission denied by user"
```

### Sub-agent inheritance

Sub-agent uses the same `handle_bash` / `handle_write` / `handle_edit`, so it inherits the same checks. A sub-agent running `ls` doesn't prompt; a sub-agent running `rm` prompts at the same TTY as the main agent.

### Adding a new tool

When adding a new tool, decide upfront whether it belongs in `ALLOWED_TOOLS` (read-only / no side effects) or not (defaults to confirm). **Default-confirm** means forgetting to update `ALLOWED_TOOLS` results in unnecessary prompts — visible, easy to fix — rather than silent auto-allow. The fail-safe direction.

---

## `prompt_user` UX

```
\033[33m{action}? (y/N): \033[0m
```

- Returns True only on explicit `y` or `yes` (case-insensitive).
- Empty / any other input / Enter → False.
- `EOFError` (piped EOF) / `KeyboardInterrupt` (Ctrl-C) → False.

The `(y/N)` capitalization signals that the default is No.

---

## Honesty About Limits

This layer catches **accidents**, not adversarial input. Known bypass surfaces:

- Variable expansion: `cmd=rm; $cmd -rf /` (validator sees `$cmd`, not `rm`).
- Base64 / encoding tricks: `echo "cm0gLXJmIC8=" | base64 -d | sh`.
- Aliases / shell functions defined in user's rc files.
- Quoted command substitution that the shlex parser can't fully resolve.

For real isolation, use a sandbox (firejail, Docker, VM). pyccode's permission layer is defense-in-depth, not a security boundary.

---

## Out of Scope (Future Tasks)

- `DENY_LIST` tier: hard-deny list for commands that should never run even with explicit consent (fork bombs, raw disk writes). Distinct from the confirm tier.
- `dangerous_callback` mechanism for positional / BSD-flag attacks (Task 3)
- TTY detection + `--allow` pre-approval flag for non-interactive use (Task 4)
- Additional allowlist commands: `find`, `sed`, `sort`, `uniq`, `date`, `git tag`/`branch` (with callback), checksum tools (Task 2)
- Path-based rules for write/edit
- Multiple `PermissionMode` values (ACCEPT_EDITS, PLAN, BYPASS)
- Audit log of confirmed actions
