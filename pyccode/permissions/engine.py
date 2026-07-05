"""Permission engine: shell-operator pre-check, flag-walking validator, tool-level decision.

Pure logic — no I/O except ``prompt_user`` (which reads stdin). The
allowlist data lives in ``pyccode.permissions.allowlist``.
"""
import re
import shlex
from dataclasses import dataclass, field


@dataclass
class CommandConfig:
    """Spec for validating one shell command (or git subcommand).

    Attributes:
        safe_flags: Maps each allowed flag to an arg-type:
            - 'none'   boolean flag, no arg consumed
            - 'string' consumes next token as required string arg
            - 'number' consumes next token as required numeric arg
            Flags not listed are rejected.
        allow_positional: If False, reject any non-flag args (for
            commands where positionals create side effects, e.g.
            future ``git tag``).
    """
    safe_flags: dict[str, str] = field(default_factory=dict)
    allow_positional: bool = True


# Tools that always pass without prompting. Everything else defaults to
# 'confirm' (default-confirm) so new tools added later don't silently bypass
# the gate just because the maintainer forgot to list them. A future
# DENY_LIST tier (true hard-deny, no prompt) is reserved.
ALLOWED_TOOLS = frozenset({"read", "TodoWrite", "skill", "run_subagent"})


# Detect shell operators / subshells / redirects that bypass argv parsing.
# `>` is matched only when not part of `>>`, `>&`, `2>` (preceded by word
# char) — conservative: any match falls through to confirm.
_SHELL_OPERATOR_PATTERN = re.compile(
    r'[;|&]|\$\(|`|(?<![<>\w])>(?![&])'
)


def _has_shell_operators(command: str) -> bool:
    """Detect shell operators / subshells / redirects that bypass argv parsing."""
    return bool(_SHELL_OPERATOR_PATTERN.search(command))


def _is_number(token: str) -> bool:
    """True if token looks like an integer (possibly negative)."""
    return token.lstrip('-').isdigit()


def _walk_flags(args: list, spec: CommandConfig) -> bool:
    """Walk args after argv[0], validating flags and consuming args per spec.

    Returns True iff every flag is in ``spec.safe_flags`` with correct
    arg consumption AND (if ``allow_positional=False``) no positional
    args remain.

    Handles:
    - ``--flag=value`` (attached long flag)
    - ``--flag value`` (detached long flag for 'string'/'number')
    - ``-f`` (short flag, 'none')
    - ``-fvalue`` (short flag with attached value)
    - ``-abc`` (short flag bundle, all must be 'none' OR last char takes arg)
    - ``--`` (end of options; rest are positional)
    """
    safe = spec.safe_flags
    i = 0
    saw_double_dash = False
    positional_count = 0

    while i < len(args):
        token = args[i]

        if saw_double_dash:
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
                    if i + 1 >= len(args):
                        return False  # flag requires arg but none given
                    next_token = args[i + 1]
                    if arg_type == 'number' and not _is_number(next_token):
                        return False
                    i += 2
        elif token.startswith('-') and len(token) > 1 and token != '-':
            # Short flag(s) — may be a bundle like -abc
            chars = token[1:]
            j = 0
            consumed_next = False
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
                        if arg_type == 'number' and not _is_number(rest_of_bundle):
                            return False
                        # Attached arg in bundle (-n5), bundle fully consumed
                    else:
                        # Need next token
                        if i + 1 >= len(args):
                            return False
                        next_token = args[i + 1]
                        if arg_type == 'number' and not _is_number(next_token):
                            return False
                        consumed_next = True
                    break  # rest of bundle consumed as arg or after arg
            i += 1 + (1 if consumed_next else 0)
        else:
            # Positional arg (including lone '-' which is often stdin)
            positional_count += 1
            i += 1

    if not spec.allow_positional and positional_count > 0:
        return False
    return True


def validate_command(command: str) -> bool:
    """Return True iff command matches READONLY_ALLOWLIST and passes flag validation.

    Never raises — malformed input returns False (falls through to confirm).
    """
    # Local import to avoid circular: allowlist imports CommandConfig from engine
    from pyccode.permissions.allowlist import READONLY_ALLOWLIST

    if _has_shell_operators(command):
        return False

    try:
        argv = shlex.split(command)
    except ValueError:
        return False

    if not argv:
        return False

    # Two-token key first (git subcommand): "git status"
    if len(argv) >= 2:
        two_token = f"{argv[0]} {argv[1]}"
        if two_token in READONLY_ALLOWLIST:
            return _walk_flags(argv[2:], READONLY_ALLOWLIST[two_token])

    # Single-token key
    if argv[0] in READONLY_ALLOWLIST:
        return _walk_flags(argv[1:], READONLY_ALLOWLIST[argv[0]])

    return False


def check_permission(tool_name: str, tool_input: dict) -> str:
    """Return 'allow' or 'confirm' for a given tool invocation.

    Default-confirm at the tool level: only tools in ``ALLOWED_TOOLS`` auto-pass.
    ``bash`` consults ``validate_command`` on ``input['command']`` for the
    read-only allowlist. Everything else (``write``, ``edit``, and any
    future mutating tool) confirms — adding a new tool without explicitly
    listing it as safe forces a prompt, which is the fail-safe direction.
    A future DENY_LIST tier (true hard-deny, no prompt even possible) is
    reserved for commands like fork bombs.
    """
    if tool_name in ALLOWED_TOOLS:
        return "allow"
    if tool_name == "bash":
        return "allow" if validate_command(tool_input.get("command", "")) else "confirm"
    return "confirm"


def prompt_user(action: str) -> bool:
    """y/N prompt. Returns True only on explicit 'y' or 'yes'.

    EOFError / KeyboardInterrupt → False (safe default: deny).
    """
    try:
        ans = input(f"\033[33m{action}? (y/N): \033[0m")
        return ans.strip().lower() in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False
