# Design — PostToolUse subprocess hook framework

## Architecture

New `pyccode/hooks/` package, parallel to `permissions/`. Three modules:

```
pyccode/hooks/
├── __init__.py     # public API re-exports
├── engine.py       # HookType, HookConfig, run_hook, run_hooks, payload builder
└── settings.py     # load_settings, SettingsSchema caching
```

Chat loop and `handle_subagent` call `run_hooks(HookType.POST_TOOL_USE, payload)`
once per `tool_result`, after handler returns, **before** `maybePersistLargeToolResult`.

## Module: `pyccode/hooks/engine.py`

### Types

```python
from dataclasses import dataclass
from enum import Enum
from typing import Any

class HookType(Enum):
    POST_TOOL_USE = "PostToolUse"
    # Future: PRE_TOOL_USE, USER_PROMPT_SUBMIT, STOP

@dataclass
class HookConfig:
    command: str           # shell command, e.g. "python3 ~/.pyccode/hooks/audit.py"
    timeout_ms: int = 5000 # subprocess timeout
    enabled: bool = True   # kill switch per-hook
```

### Payload builder

```python
def build_post_tool_use_payload(
    *,
    tool_name: str,
    tool_use_id: str,
    tool_input: dict,
    tool_response: str,
    agent_id: str,  # "main" or "subagent"
) -> dict:
    return {
        "hook_event_name": HookType.POST_TOOL_USE.value,
        "session_id": SESSION_ID,
        "transcript_path": str(TRANSCRIPT_PATH),
        "cwd": str(WORKDIR),
        "permission_mode": PermissionMode.DEFAULT.value,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent_id": agent_id,
        "tool_name": tool_name,
        "tool_use_id": tool_use_id,
        "tool_input": tool_input,
        "tool_response": tool_response,
        "tool_error": tool_response.startswith("Error:"),
    }
```

### Hook executor

```python
@dataclass
class HookOutcome:
    exit_code: int
    timed_out: bool
    stdout: str
    stderr: str

def run_hook(config: HookConfig, payload: dict) -> HookOutcome:
    """Run one hook subprocess. Never raises; failures are captured in outcome."""
    try:
        proc = subprocess.run(
            config.command,
            shell=True,
            input=json.dumps(payload, ensure_ascii=False),
            capture_output=True,
            text=True,
            timeout=config.timeout_ms / 1000,
            encoding='utf-8',
        )
        return HookOutcome(
            exit_code=proc.returncode,
            timed_out=False,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )
    except subprocess.TimeoutExpired as e:
        return HookOutcome(exit_code=-1, timed_out=True, stdout="", stderr=str(e))
    except Exception as e:
        return HookOutcome(exit_code=-2, timed_out=False, stdout="", stderr=str(e))


def run_hooks(event: HookType, payload: dict) -> None:
    """Dispatch to all configured hooks for this event type. Never raises."""
    settings = load_settings()
    hooks = settings.hooks.get(event.value, [])
    for cfg in hooks:
        if not cfg.enabled:
            continue
        outcome = run_hook(cfg, payload)
        if outcome.timed_out:
            print(f"\033[33m[Hook '{cfg.command}' timed out after {cfg.timeout_ms}ms]\033[0m",
                  file=sys.stderr)
        elif outcome.exit_code != 0:
            print(f"\033[33m[Hook '{cfg.command}' failed: exit {outcome.exit_code}]\033[0m",
                  file=sys.stderr)
            if outcome.stderr:
                print(f"\033[33m{outcome.stderr.strip()}\033[0m", file=sys.stderr)
```

## Module: `pyccode/hooks/settings.py`

```python
from dataclasses import dataclass, field
from pathlib import Path
import json

SETTINGS_PATH = Path.home() / ".pyccode" / "settings.json"

@dataclass
class SettingsSchema:
    hooks: dict[str, list[HookConfig]] = field(default_factory=dict)
    raw: dict = field(default_factory=dict)  # original JSON for forward-compat

_settings_cache: SettingsSchema | None = None

def load_settings(force_reload: bool = False) -> SettingsSchema:
    global _settings_cache
    if _settings_cache is not None and not force_reload:
        return _settings_cache
    try:
        raw = json.loads(SETTINGS_PATH.read_text(encoding='utf-8')) if SETTINGS_PATH.exists() else {}
    except Exception as e:
        print(f"\033[33m[Settings load failed: {e}]\033[0m", file=sys.stderr)
        raw = {}
    hooks_raw = raw.get("hooks", {}) or {}
    hooks: dict[str, list[HookConfig]] = {}
    for event_name, hook_list in hooks_raw.items():
        parsed = []
        for h in hook_list or []:
            try:
                parsed.append(HookConfig(
                    command=h["command"],
                    timeout_ms=int(h.get("timeout_ms", 5000)),
                    enabled=bool(h.get("enabled", True)),
                ))
            except (KeyError, ValueError) as e:
                print(f"\033[33m[Settings: skipping malformed hook {h!r}: {e}]\033[0m",
                      file=sys.stderr)
        hooks[event_name] = parsed
    _settings_cache = SettingsSchema(hooks=hooks, raw=raw)
    return _settings_cache
```

Cache is module-level. `force_reload=True` reserved for future `/reload-hooks`
REPL command.

## Module: `pyccode/hooks/__init__.py`

```python
from .engine import HookType, HookConfig, HookOutcome, run_hook, run_hooks, build_post_tool_use_payload
from .settings import load_settings, SettingsSchema, SETTINGS_PATH

__all__ = [
    "HookType", "HookConfig", "HookOutcome",
    "run_hook", "run_hooks", "build_post_tool_use_payload",
    "load_settings", "SettingsSchema", "SETTINGS_PATH",
]
```

## Integration Points

### `chat()` — main agent loop (in `pyccode/chat.py`)

After the tool execution loop builds `results`, before
`maybePersistLargeToolResult`:

```python
results = []
for content in response.content:
    if content.type == "tool_use":
        handler = TOOL_HANDLERS.get(content.name)
        output = handler(content.input) if handler else f"Error: Unknown tool: {content.name}"
        # HOOK INTEGRATION: fire PostToolUse per result, before Layer 1
        run_hooks(HookType.POST_TOOL_USE, build_post_tool_use_payload(
            tool_name=content.name,
            tool_use_id=content.id,
            tool_input=content.input,
            tool_response=output,
            agent_id="main",
        ))
        results.append({
            "type": "tool_result",
            "tool_use_id": content.id,
            "content": maybePersistLargeToolResult(content.id, output),
        })
```

### `handle_subagent()` — sub-agent loop (in `pyccode/chat.py`)

Same insertion, `agent_id="subagent"`.

## Failure Modes

| Scenario | Behavior |
|---|---|
| `~/.pyccode/settings.json` missing | `load_settings` returns empty; no hooks fire |
| `settings.json` malformed JSON | stderr warning; behave as empty |
| Hook entry missing `command` key | skip that entry, stderr warning |
| `timeout_ms` not integer | skip + stderr warning |
| Subprocess non-zero exit | stderr `[Hook '<cmd>' failed: exit N]`; chat continues |
| Subprocess timeout | killed; stderr `[Hook '<cmd>' timed out after Xms]`; chat continues |
| Subprocess can't spawn (e.g. command not found) | captured as exit_code != 0, same stderr format |
| Payload serialization fails (shouldn't happen) | skip the hook call, stderr warning |

**Never propagate exceptions to chat loop.** All paths through `run_hooks`
return `None`; the chat loop is unaffected.

## Trade-offs

- **Subprocess vs in-process**: subprocess adds ~50ms per hook (process
  spawn + Python interpreter startup if Python). For audit-style hooks
  firing every tool call, this is acceptable. Trade-off: language-agnostic
  + isolated (hook crash doesn't take down pyccode) vs latency. Matches
  Claude Code semantics — this is the精髓 to learn.

- **Read-only MVP**: hooks cannot modify `tool_response` or veto. Real
  secret masking (replace, not warn) needs this. Deferred to a future
  task that introduces the stdout JSON output contract.

- **Serial execution**: multiple PostToolUse hooks run one after another.
  Total latency = sum. Parallel would complicate error handling and
  output ordering. Defer.

- **Settings cached at startup**: changes to `settings.json` mid-session
  require restart. Live reload is a future feature.

- **No project-local override**: a project can't ship its own
  `.pyccode/settings.json` for VCS-tracked hooks. Future task.

## Compatibility

- No external API change to chat loop other than the inserted `run_hooks`
  call. All existing tests / behaviors unchanged if no hooks configured.
- `~/.pyccode/settings.json` is new; absence = no hooks = current
  behavior.
- Payload schema documented in PRD; future hooks (PreToolUse etc.) will
  reuse most fields with event-specific additions.
