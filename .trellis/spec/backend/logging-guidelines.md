# Logging Guidelines

> pyccode has no logging framework. All operator output is plain `print` to stdout, ANSI-colored.

---

## No Log Levels

There is no debug / info / warn / error distinction. Everything goes to stdout. The model sees what the operator sees. If you need filtering, pipe through shell tools (`grep`, `awk`).

---

## ANSI Color Convention

Every handler prints at least one yellow (`\033[33m`) status line before doing its work. Established prefixes — search this table before inventing new ones:

| Prefix | Where | Example |
|---|---|---|
| `$ <cmd>` | `handle_bash` (pyccode.py:295) | `$ ls -la` |
| `Read: <path>` | `handle_read` (pyccode.py:330) | `Read: /tmp/foo.txt` |
| `Write: <path>` | `handle_write` (pyccode.py:374) | `Write: src/app.py` |
| `Edit: <path>` | `handle_edit` (pyccode.py:408) | `Edit: pyccode.py` |
| `Todo: updated <N> task(s)` | `handle_todo` (pyccode.py:446) | `Todo: updated 3 task(s)` |
| `[Subagent] <prompt-preview>` | `handle_subagent` (pyccode.py:466) | `[Subagent] explore src/...` |
| `[Subagent] Done` | `handle_subagent` (pyccode.py:509) | end-of-loop marker |
| `Skill: <name>` | `handle_skill` (pyccode.py:552) | `Skill: commit` |
| `[Tool result persisted: <N> chars -> <path>]` | `maybePersistLargeToolResult` (pyccode.py:609) | persistence notice |
| `Error: <message>` | unknown-tool branch (pyccode.py:698) | `Error: Unknown tool: foo` |

Cyan (`\033[36m`) is reserved for the REPL prompt (`>> `). Reset with `\033[0m` on the same line.

---

## What to Print

- **Always**: the subject of the action (path, command, skill name) before the action.
- **Always**: the final output before returning it, so stdout mirrors the model's view.
- **Never**: secrets. `.env` values, API keys, model responses that may contain echoed secrets — do not print.

---

## Anti-Patterns

- **Inventing a new color / prefix** for a one-off message. Reuse the table above or extend it deliberately with a new row.
- **Printing to stderr.** Operators tail stdout; stderr is reserved for Python tracebacks (which we prevent by not raising).
- **`logging` module.** Not used. Adding it would fragment the output stream and compete with the existing print-based convention.
