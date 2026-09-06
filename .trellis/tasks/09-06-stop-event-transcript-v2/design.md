# Design — Transcript v2 via internal MessageAppend hook

## Architecture

No new modules. Changes concentrated in two existing files:

```
pyccode/hooks/engine.py          # + HookType.MESSAGE_APPEND, internal registry, dispatch split
pyccode/hooks/settings.py        # + EXTERNAL_EVENTS gate
pyccode/context/transcript.py    # appendTranscript(+usage, +gitBranch); history_append
                                 #   fires MessageAppend; transcript hook + registration
pyccode/chat.py                  # pass usage dict to history_append (assistant turns only)
```

## Internal registry (hooks/engine.py)

```python
InternalHook = Callable[[dict], None]
_internal_hooks: dict[HookType, list[InternalHook]] = {}

def register_internal_hook(event: HookType, fn: InternalHook) -> None:
    _internal_hooks.setdefault(event, []).append(fn)

def _run_internal(event: HookType, payload: dict) -> None:
    for fn in _internal_hooks.get(event, []):
        try:
            fn(payload)
        except Exception as e:
            print(f"\033[33m[Internal hook {fn.__name__!r} failed: {e}]\033[0m",
                  file=sys.stderr)

def run_hooks(event: HookType, payload: dict) -> None:
    _run_internal(event, payload)   # internal first: fast, state-carrying
    _run_external(event, payload)   # then subprocess hooks
```

`_run_external` = current dispatch body, extracted.

## External gating (hooks/settings.py)

```python
EXTERNAL_EVENTS = frozenset({"PostToolUse"})
```

`load_settings` skips + warns on event names outside this set. `MessageAppend`
configured in settings.json → `[Settings: event 'MessageAppend' is internal-only, skipping]`.
Adding `Stop` later = add to this set.

## MessageAppend + transcript hook (context/transcript.py)

```python
def history_append(history: list, role: str, content, usage: dict | None = None) -> None:
    """Append a message to history; fires MessageAppend (transcript writes there)."""
    history.append({"role": role, "content": content})
    run_hooks(HookType.MESSAGE_APPEND, {
        "hook_event_name": HookType.MESSAGE_APPEND.value,
        "session_id": SESSION_ID,
        "cwd": str(WORKDIR),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "role": role,
        "content": content,
        "usage": usage,
    })


def appendTranscript(role: str, content, usage: dict | None = None) -> None:
    """(existing docstring) + usage embedded on assistant entries; gitBranch on all."""
    ...  # existing body, plus:
    # entry["gitBranch"] = _read_git_branch()
    # if role == "assistant" and usage is not None:
    #     entry["message"]["usage"] = usage


def _read_git_branch() -> str | None:
    """Parse .git/HEAD for the branch name. None if not a repo / detached / worktree."""
    try:
        text = (WORKDIR / ".git" / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text[len("ref: refs/heads/"):] if text.startswith("ref: refs/heads/") else None


def _transcript_message_append_hook(payload: dict) -> None:
    appendTranscript(payload["role"], payload["content"], usage=payload.get("usage"))


register_internal_hook(HookType.MESSAGE_APPEND, _transcript_message_append_hook)
```

Registration at module bottom = the single registration site. Importing
`pyccode.context.transcript` (which `pyccode.chat` does) activates it.

## Import graph (no cycles)

```
hooks.engine     → config            (leaf)
hooks.settings   → hooks.engine
context.transcript → config, hooks.engine
chat             → context, hooks, tools, config
```

`hooks.engine` never imports `context` — the cycle is impossible.

## chat() usage pass-through

```python
if response.usage:
    usage_dict = {
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    }
else:
    usage_dict = None
history_append(history, "assistant", assistant_content, usage=usage_dict)
```

All other `history_append` call sites unchanged (default usage=None).

## Failure modes

| Scenario | Behavior |
|---|---|
| Internal hook raises | stderr `[Internal hook ... failed]`; history append already happened; chat continues |
| settings.json configures MessageAppend | skipped + warning; no subprocess |
| .git/HEAD unreadable / detached / worktree | gitBranch=None |
| Transcript write fails | existing per-entry try/except; stderr notice |
| usage missing (no response.usage) | entry omits message.usage |

## Trade-offs

- **Per-append .git/HEAD read**: one small file read per message; negligible
  at conversation frequency; always fresh (agent may `git checkout` mid-turn).
- **Side-effect registration on import**: implicit, but one documented site;
  matches how SKILLS already loads at import.
- **history_append keeps its name/shape** (plus optional usage): call sites
  untouched except chat()'s assistant turn.

## Compatibility

- Transcript schema additive (`gitBranch`, `message.usage`).
- External PostToolUse unchanged.
- v1 incremental write timing preserved exactly — crash loss is one entry.
