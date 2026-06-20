# Tool Handler Conventions

> Every tool exposed to the model is backed by a handler with a fixed shape. This spec is the contract.

---

## Signature

```python
def handle_<name>(input: dict) -> str:
    ...
```

- `input`: the `tool_use.input` dict from the Anthropic API. Untyped on purpose — the schema validates upstream.
- Returns: a single string. The chat loop wraps it as `tool_result.content`.

No handler raises. Errors are returned as `"Error: ..."` strings so the agent can react.

---

## Required Skeleton

Every handler follows the same shape (see `handle_read` and `handle_write`):

```python
def handle_<name>(input: dict) -> str:
    """One-line summary.

    Longer description.

    Args:
        input: A dict containing:
            <key> (<type>): <purpose>.

    Returns:
        <what the string represents, including the error format>.
    """
    <extract fields from input>
    print(f"\033[33m<Verb>: <subject>\033[0m")
    try:
        <do the work>
    except <SpecificError> as e:
        output = f"Error: <description>: {<path>}"
    except Exception as e:
        output = f"Error: {e}"
    if not output:
        output = "(empty)"
    print(output)
    return output
```

Conventions:

- Print a yellow `Verb: subject` line first so the operator sees what is happening. See [logging-guidelines.md](./logging-guidelines.md) for the prefix table.
- Print the final output before returning, so stdout mirrors what the model receives.
- Convert empty output to `"(empty)"` — never return `""`. The model treats empty tool results as ambiguous.
- Catch specific filesystem errors first (`FileNotFoundError`, `IsADirectoryError`, `PermissionError`), then broad `Exception` as a safety net.
- Always include the offending path/command/name in error messages.

---

## Anti-Patterns

- **Raising exceptions.** The chat loop does not catch handler exceptions; an uncaught raise aborts the agent. Always convert to an error string.
- **Returning non-str.** The Anthropic API rejects non-string `tool_result.content` for our schema mix.
- **Silent success.** A handler that does its work without printing leaves the operator blind. Always log at least the subject.
- **Mutating `input`.** Treat it as read-only.

---

## Tool Result Size

Handlers return the full output. Size reduction is the chat loop's job, not the handler's. See [chat-loop.md](./chat-loop.md) for the `maybePersistLargeToolResult` contract.

---

## Subagent Handler Exception

`handle_subagent` is the one handler that breaks the shape above: it runs its own agentic loop, manages its own message list, and returns the sub-agent's final text rather than a status string. It also swaps `_task_store` inside a `try` / `finally`. Do not collapse it into the standard skeleton.
