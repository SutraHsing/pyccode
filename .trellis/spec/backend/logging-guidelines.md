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
| `$ <cmd>` | `handle_bash` | `$ ls -la` |
| `Read: <path>` | `handle_read` | `Read: /tmp/foo.txt` |
| `Write: <path>` | `handle_write` | `Write: src/app.py` |
| `Edit: <path>` | `handle_edit` | `Edit: pyccode.py` |
| `Todo: updated <N> task(s)` | `handle_todo` | `Todo: updated 3 task(s)` |
| `[Subagent] <prompt-preview>` | `handle_subagent` (start) | `[Subagent] explore src/...` |
| `[Subagent] Done` | `handle_subagent` (end) | end-of-loop marker |
| `Skill: <name>` | `handle_skill` | `Skill: commit` |
| `[Tool result persisted: <N> chars -> <path>]` | `_persist_tool_result` | persistence notice |
| `[Auto-compact: history reduced to <N> messages]` | `maybeAutoCompact` (success) | `[Auto-compact: history reduced to 6 messages]` |
| `[Auto-compact failed: <reason>]` | `maybeAutoCompact` (to **stderr**) | `[Auto-compact failed: network down]` |
| `[Transcript write failed: <error>]` | `appendTranscript` (to **stderr**) | `[Transcript write failed: ...]` |
| `Error: <message>` | `chat()` (unknown-tool branch) | `Error: Unknown tool: foo` |

Cyan (`\033[36m`) is reserved for the REPL prompt (`>> `). Reset with `\033[0m` on the same line.

Two prefixes are routed to **stderr**, not stdout: `[Transcript write failed: ...]` and `[Auto-compact failed: ...]`. Both signal side-channel failures that must not muddy the handler-output stream.

`[Transcript write failed: ...]` is the one prefix routed to **stderr**, not stdout — handler output and transcript logging share the stdout stream convention, so the failure notice goes elsewhere to avoid muddying it.

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
