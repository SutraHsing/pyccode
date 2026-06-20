# Error Handling

> Handlers return error strings; the chat loop never crashes on tool failures.

---

## Convention

Tool handlers do not raise. Errors are returned as `"Error: <description>"` strings, and the agent decides how to react. This is the load-bearing contract of the whole project.

Pattern (see `handle_read` and `handle_edit`):

```python
try:
    <work>
except FileNotFoundError:
    output = f"Error: File not found: {file_path}"
except PermissionError:
    output = f"Error: Permission denied: {file_path}"
except Exception as e:
    output = f"Error: {e}"
```

Rules:

- Catch specific errors first; `Exception` last as a safety net.
- Always include the offending input (path, command, name) in the message.
- Prefix with `"Error: "` so the agent can pattern-match.
- Do not re-raise.

---

## Bash Handler Exception

`handle_bash` cannot enumerate every failure mode. It captures `subprocess.run` stdout + stderr and lets the model interpret. Only `TimeoutExpired` is converted explicitly:

```python
except subprocess.TimeoutExpired:
    output = "(timeout after 300s)"
```

Bash also encodes bytes defensively before returning:

```python
output = output.encode('utf-8', errors='replace').decode('utf-8')
```

---

## Persistence Failure

`_persist_tool_result` wraps its filesystem work in `try` / `except`. On failure, it returns the legacy 50K truncation with `[persist failed: <error>]` appended. Persistence errors never propagate into the chat loop. Both `maybePersistLargeToolResult` and `enforceToolResultBudget` inherit this behavior because they delegate to `_persist_tool_result`.

---

## Subagent Isolation

`handle_subagent` swaps `_task_store` inside a `try` and restores it in `finally`. If the sub-agent raises mid-loop, the main agent's task store survives. Any new global swap must follow the same pattern.

---

## Anti-Patterns

- **Raising from a handler.** Will crash the REPL / single-prompt run.
- **Returning `None`.** The API rejects the tool_result. Return `"(empty)"` for no-output cases.
- **Silent fallbacks.** Catching `Exception` and continuing without telling the model is forbidden — always encode the failure in the returned string.
- **Bare `except:`.** Use `except Exception as e:` so we do not swallow `KeyboardInterrupt`.
