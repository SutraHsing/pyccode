"""Curated allowlist of read-only shell commands.

Each entry maps a command name (or ``git <subcommand>``) to a
``CommandConfig``. The validator in ``engine.py`` accepts only the
flags listed here, with the arg-types declared.

Task 1 scope: ls / cat / pwd / grep / git status / git log. Future
tasks expand this list and add the ``dangerous_callback`` mechanism
needed for commands like ``find`` (blocks ``-delete`` / ``-exec``),
``git tag`` / ``git branch`` (blocks positional ref creation), and
``date`` (blocks positional time-set).
"""
from pyccode.permissions.engine import CommandConfig


READONLY_ALLOWLIST: dict[str, CommandConfig] = {
    "ls": CommandConfig(safe_flags={
        # Display
        "-l": "none", "-a": "none", "-la": "none", "-lh": "none",
        "-R": "none", "-t": "none", "-S": "none", "-h": "none",
        "-r": "none", "-F": "none", "-1": "none",
        "--color": "string",
    }),
    "cat": CommandConfig(safe_flags={
        "-n": "none", "-b": "none", "-s": "none",
        "-A": "none", "-E": "none", "-T": "none", "-v": "none",
    }),
    "pwd": CommandConfig(safe_flags={
        "-L": "none", "-P": "none",
    }),
    "grep": CommandConfig(safe_flags={
        # Pattern flags
        "-e": "string", "-f": "string",
        "--regexp": "string", "--file": "string",
        "-F": "none", "--fixed-strings": "none",
        "-G": "none", "--basic-regexp": "none",
        "-E": "none", "--extended-regexp": "none",
        "-P": "none", "--perl-regexp": "none",
        # Match control
        "-i": "none", "--ignore-case": "none",
        "-v": "none", "--invert-match": "none",
        "-w": "none", "--word-regexp": "none",
        "-x": "none", "--line-regexp": "none",
        # Output control
        "-c": "none", "--count": "none",
        "--color": "string", "--colour": "string",
        "-L": "none", "--files-without-match": "none",
        "-l": "none", "--files-with-matches": "none",
        "-m": "number", "--max-count": "number",
        "-o": "none", "--only-matching": "none",
        "-q": "none", "--quiet": "none",
        "-s": "none", "--no-messages": "none",
        # Output prefix
        "-b": "none", "--byte-offset": "none",
        "-H": "none", "--with-filename": "none",
        "-h": "none", "--no-filename": "none",
        "--label": "string",
        "-n": "none", "--line-number": "none",
        "-T": "none", "--initial-tab": "none",
        "-u": "none", "--unix-byte-offsets": "none",
        "-Z": "none", "--null": "none",
        "-z": "none", "--null-data": "none",
        # Context
        "-A": "number", "--after-context": "number",
        "-B": "number", "--before-context": "number",
        "-C": "number", "--context": "number",
        "--group-separator": "string", "--no-group-separator": "none",
        # File/dir selection
        "-a": "none", "--text": "none",
        "--binary-files": "string",
        "-D": "string", "--devices": "string",
        "-d": "string", "--directories": "string",
        "--exclude": "string", "--exclude-from": "string",
        "--exclude-dir": "string", "--include": "string",
        "-r": "none", "--recursive": "none",
        "-R": "none", "--dereference-recursive": "none",
        # Misc
        "--line-buffered": "none",
        "-U": "none", "--binary": "none",
        # Help / version
        "--help": "none",
        "-V": "none", "--version": "none",
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
        "--oneline": "none",
        "-p": "none", "--patch": "none",
        "--stat": "none", "--shortstat": "none",
        "--graph": "none", "--no-decorate": "none",
        "-n": "number", "--max-count": "number",
        "--skip": "number",
        "--author": "string", "--grep": "string",
        "--since": "string", "--after": "string",
        "--until": "string", "--before": "string",
        "--pretty": "string", "--format": "string",
        "--abbrev-commit": "none", "--no-abbrev-commit": "none",
        "--first-parent": "none",
        "--no-merges": "none", "--merges": "none",
        "--reverse": "none", "--all": "none",
        "-S": "string", "-G": "string",
        "--date": "string",
        "--name-only": "none", "--name-status": "none",
    }),
}
