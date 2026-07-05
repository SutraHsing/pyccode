# Design — Permission framework: allowlist + flag validation

## Architecture

Two new modules under `pyccode/permissions/`. Engine is pure logic;
allowlist is data. Handlers import `check_permission` and `prompt_user`.

```
pyccode/tools/bash.py    ───┐
pyccode/tools/file.py    ───┼──► pyccode.permissions.check_permission
pyccode/chat.py          ───┘                  │
                                              ▼
                            pyccode/permissions/engine.py
                                       │
                                       ▼
                            pyccode/permissions/allowlist.py
```

No cycles: permissions imports only stdlib + `pyccode.config` (none in
Task 1, actually — pure stdlib).

## Module: `pyccode/permissions/engine.py`

### `CommandConfig`

```python
from dataclasses import dataclass, field

@dataclass
class CommandConfig:
    """Spec for validating one shell command (or git subcommand)."""
    safe_flags: dict[str, str] = field(default_factory=dict)
    allow_positional: bool = True
```

`safe_flags` maps each allowed flag to an arg-type:
- `'none'` — boolean flag, no arg consumed
- `'string'` — consumes next token as required string arg
- `'number'` — consumes next token as required numeric arg

Flags not in `safe_flags` are rejected.

`allow_positional=False` rejects any non-flag args (for future commands
like `git tag`/`git branch` where positionals create refs).

### Shell operator pre-check

```python
import re

_SHELL_OPERATOR_PATTERN = re.compile(
    r'[;|&]|\$\(|`|(?<![<>\w])>(?![&])'
)

def _has_shell_operators(command: str) -> bool:
    """Detect shell operators / subshells / redirects that bypass argv parsing."""
    return bool(_SHELL_OPERATOR_PATTERN.search(command))
```

The `(?<![<>\w])>(?![&])` regex matches a `>` that's not part of `>>`,
`>&`, `2>`, or preceded by a word char (to avoid false positives inside
words). Conservative: any match → fall through to confirm.

### Flag-walking parser

```python
import shlex

def _walk_flags(args: list[str], spec: CommandConfig) -> bool:
    """Walk args after argv[0], validating flags and consuming args per spec.

    Returns True if every flag is in safe_flags with correct arg consumption
    AND (if allow_positional=False) no positional args remain.
    """
    safe = spec.safe_flags
    i = 0
    saw_double_dash = False
    positional_count = 0

    while i < len(args):
        token = args[i]

        if saw_double_dash:
            # Everything after `--` is positional
            positional_count += 1
            i += 1
            continue

        if token == '--':
            saw_double_dash = True
            i += 1
            continue

        if token.startswith('--'):
            # Long flag
            if '=' in token:
                # --flag=value (attached)
                flag_name = token.split('=', 1)[0]
                if flag_name not in safe:
                    return False
                # arg-type doesn't matter — value is attached
                i += 1
            else:
                if token not in safe:
                    return False
                arg_type = safe[token]
                if arg_type == 'none':
                    i += 1
                else:  # 'string' or 'number'
                    # Need to consume next token as arg
                    if i + 1 >= len(args):
                        return False  # flag requires arg but none given
                    next_token = args[i + 1]
                    if arg_type == 'number' and not next_token.lstrip('-').isdigit():
                        return False
                    i += 2
        elif token.startswith('-') and len(token) > 1:
            # Short flag(s) — may be a bundle like -abc
            chars = token[1:]
            j = 0
            consumed_arg = False
            while j < len(chars):
                short = '-' + chars[j]
                if short not in safe:
                    return False
                arg_type = safe[short]
                if arg_type == 'none':
                    j += 1
                else:
                    # 'string' or 'number' — rest of bundle is the arg,
                    # or next token if bundle is exhausted
                    rest_of_bundle = chars[j + 1:]
                    if rest_of_bundle:
                        if arg_type == 'number' and not rest_of_bundle.lstrip('-').isdigit():
                            return False
                        # Attached arg in bundle (-n5), consume rest of bundle
                    else:
                        # Need next token
                        if i + 1 >= len(args):
                            return False
                        next_token = args[i + 1]
                        if arg_type == 'number' and not next_token.lstrip('-').isdigit():
                            return False
                        consumed_arg = True
                    break  # rest of bundle consumed as arg or after arg
            i += 1 + (1 if consumed_arg else 0)
        else:
            # Positional arg
            positional_count += 1
            i += 1

    if not spec.allow_positional and positional_count > 0:
        return False
    return True
```

### `validate_command`

```python
def validate_command(command: str) -> bool:
    """Return True iff command is in READONLY_ALLOWLIST and passes flag validation."""
    if _has_shell_operators(command):
        return False

    try:
        argv = shlex.split(command)
    except ValueError:
        return False

    if not argv:
        return False

    # Check two-token key first (git subcommand): "git status"
    if len(argv) >= 2:
        two_token = f"{argv[0]} {argv[1]}"
        if two_token in READONLY_ALLOWLIST:
            return _walk_flags(argv[2:], READONLY_ALLOWLIST[two_token])

    # Single-token key
    if argv[0] in READONLY_ALLOWLIST:
        return _walk_flags(argv[1:], READONLY_ALLOWLIST[argv[0]])

    return False
```

Two-token check first so `git status` matches before falling through to
bare `git`.

### `check_permission` and `prompt_user`

```python
CONFIRM_TOOLS = frozenset({"bash", "write", "edit"})

def check_permission(tool_name: str, tool_input: dict) -> str:
    """Return 'allow' or 'confirm'."""
    if tool_name not in CONFIRM_TOOLS:
        return "allow"
    if tool_name == "bash":
        return "allow" if validate_command(tool_input.get("command", "")) else "confirm"
    return "confirm"


def prompt_user(action: str) -> bool:
    """y/N prompt. Returns True only on explicit yes."""
    try:
        ans = input(f"\033[33m{action}? (y/N): \033[0m")
        return ans.strip().lower() in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False
```

## Module: `pyccode/permissions/allowlist.py`

Six commands for Task 1. Each `safe_flags` dict is the curated set of
flags that don't mutate state.

```python
from pyccode.permissions.engine import CommandConfig

def _argtype_flags(**none_flags):
    """Helper: build dict of flag→'none'."""
    return {f: "none" for f in none_flags}

READONLY_ALLOWLIST: dict[str, CommandConfig] = {
    "ls": CommandConfig(safe_flags={
        "-l": "none", "-a": "none", "-la": "none", "-lh": "none",
        "-R": "none", "-t": "none", "-S": "none", "-h": "none",
        "-r": "none", "--color": "string",
        "-F": "none", "-1": "none",
    }),
    "cat": CommandConfig(safe_flags={
        "-n": "none", "-b": "none", "-s": "none", "-A": "none",
        "-E": "none", "-T": "none", "-v": "none",
    }),
    "pwd": CommandConfig(safe_flags={
        "-L": "none", "-P": "none",
    }),
    "grep": CommandConfig(safe_flags={
        # pattern flags
        "-e": "string", "-f": "string", "--regexp": "string",
        "--file": "string",
        "-F": "none", "--fixed-strings": "none",
        "-G": "none", "--basic-regexp": "none",
        "-E": "none", "--extended-regexp": "none",
        "-P": "none", "--perl-regexp": "none",
        # match control
        "-i": "none", "--ignore-case": "none",
        "-v": "none", "--invert-match": "none",
        "-w": "none", "--word-regexp": "none",
        "-x": "none", "--line-regexp": "none",
        # output control
        "-c": "none", "--count": "none",
        "--color": "string", "--colour": "string",
        "-L": "none", "-l": "none", "-m": "number",
        "-o": "none", "-q": "none", "-s": "none",
        # output prefix
        "-b": "none", "-H": "none", "-h": "none", "-n": "none",
        "-T": "none", "-u": "none", "-Z": "none", "-z": "none",
        "--label": "string",
        # context
        "-A": "number", "-B": "number", "-C": "number",
        # file/dir selection
        "-a": "none", "--binary-files": "string", "-D": "string",
        "-d": "string", "--exclude": "string", "--exclude-from": "string",
        "--exclude-dir": "string", "--include": "string",
        "-r": "none", "-R": "none",
        # misc
        "--line-buffered": "none", "-U": "none",
    }),
    "git status": CommandConfig(safe_flags={
        "-s": "none", "--short": "none",
        "-b": "none", "--branch": "none",
        "--porcelain": "none", "--long": "none",
        "-v": "none", "--verbose": "none",
        "--untracked-files": "string", "-u": "string",
        "--ignored": "none", "--ignore-submodules": "string",
        "--column": "none", "--no-column": "none",
        "--ahead-behind": "none", "--no-ahead-behind": "none",
        "--renames": "none", "--no-renames": "none",
        "--find-renames": "string", "-M": "string",
    }),
    "git log": CommandConfig(safe_flags={
        "--oneline": "none", "-p": "none", "--patch": "none",
        "--stat": "none", "--shortstat": "none",
        "--graph": "none", "--no-decorate": "none",
        "-n": "number", "--max-count": "number",
        "--skip": "number", "--author": "string",
        "--grep": "string", "--since": "string", "--after": "string",
        "--until": "string", "--before": "string",
        "--pretty": "string", "--format": "string",
        "--abbrev-commit": "none", "--no-abbrev-commit": "none",
        "--first-parent": "none", "--no-merges": "none", "--merges": "none",
        "--reverse": "none", "--all": "none",
        "-S": "string", "-G": "string",
        "--date": "string", "--name-only": "none", "--name-status": "none",
    }),
}
```

## Integration

### `pyccode/tools/bash.py`

```python
from pyccode.permissions import check_permission, prompt_user

def handle_bash(input):
    command = input["command"]
    if check_permission("bash", input) == "confirm":
        if not prompt_user(f"Run bash: {command}"):
            return "Error: Permission denied by user"
    # ... existing subprocess.run logic unchanged
```

### `pyccode/tools/file.py`

```python
from pyccode.permissions import check_permission, prompt_user

def handle_write(input):
    file_path = input["file_path"]
    if not prompt_user(f"Write to {file_path}"):
        return "Error: Permission denied by user"
    # ... existing write logic

def handle_edit(input):
    file_path = input["file_path"]
    if not prompt_user(f"Edit {file_path}"):
        return "Error: Permission denied by user"
    # ... existing edit logic
```

(write/edit always confirm, no need to call `check_permission` for them —
but using `check_permission` first keeps the pattern uniform. For MVP,
direct `prompt_user` call is simpler.)

### `pyccode/permissions/__init__.py`

```python
from .engine import (
    CommandConfig,
    check_permission,
    prompt_user,
    validate_command,
)
from .allowlist import READONLY_ALLOWLIST
```

## Failure Modes

| Scenario | Behavior |
|---|---|
| Empty command string | `validate_command` returns False → confirm |
| `shlex.split` raises (unbalanced quotes) | Caught, returns False → confirm |
| Shell operator present | Pre-check rejects → confirm |
| Unknown flag in allowed command | Flag walker returns False → confirm |
| Missing arg for `'string'`/`'number'` flag | Walker returns False → confirm |
| Non-numeric arg for `'number'` flag | Walker returns False → confirm |
| `prompt_user` gets EOF (piped input) | Returns False → "Permission denied" |
| User presses Ctrl-C at prompt | Returns False → "Permission denied" |

## Trade-offs

- **No callback mechanism (Task 1)**: can't safely include `find` /
  `git tag` / `git branch` / `date` — they need positional-arg or
  dangerous-flag blocking. Acceptable; they fall through to confirm,
  user decides per call.
- **No TTY detection**: assumes user is present. Future `--allow` flag
  or non-interactive mode is separate work.
- **Substring false positives in operator regex**: `cat "a > b"` (literal
  `>` in quoted string) triggers fall-through to confirm. Conservative
  direction — better than the alternative.
- **`safe_flags` maintenance**: each command's flag list must be
  curated. Missing a safe flag → user sees unnecessary prompts. Better
  than the inverse.
- **No path-based rules for write/edit**: all writes prompt, even to
  `/tmp/test.txt`. Simple. Can refine in future.

## Compatibility

- No external API change.
- No new on-disk artifacts.
- One new package: `pyccode/permissions/`.
- Conversation history semantics unchanged — handlers return
  `"Error: Permission denied by user"` strings, which the agent can
  react to like any other error.
