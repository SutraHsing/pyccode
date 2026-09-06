"""Hook engine: type enum, config, executor, dispatcher, payload builder."""
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from pyccode.config import SESSION_ID, TRANSCRIPT_PATH, WORKDIR


class HookType(Enum):
    """Event types that can fire hooks. MVP: only POST_TOOL_USE."""
    POST_TOOL_USE = "PostToolUse"
    # Future: PRE_TOOL_USE, USER_PROMPT_SUBMIT, STOP


@dataclass
class HookConfig:
    """One hook entry from settings.json."""
    command: str
    timeout_ms: int = 5000
    enabled: bool = True


@dataclass
class HookOutcome:
    """Result of running one hook subprocess."""
    exit_code: int
    timed_out: bool
    stdout: str
    stderr: str


def build_post_tool_use_payload(
    *,
    tool_name: str,
    tool_use_id: str,
    tool_input: dict,
    tool_response: str,
    agent_id: str,
) -> dict:
    """Assemble the 12-field PostToolUse payload (see PRD schema table)."""
    # Local import to avoid circular: permissions package imports nothing
    # from hooks, but deferring keeps engine a leaf module.
    from pyccode.permissions.engine import PermissionMode

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


def run_hook(config: HookConfig, payload: dict) -> HookOutcome:
    """Run one hook subprocess. Never raises; failures land in the outcome."""
    try:
        proc = subprocess.run(
            config.command,
            shell=True,
            input=json.dumps(payload, ensure_ascii=False),
            capture_output=True,
            text=True,
            timeout=config.timeout_ms / 1000,
            encoding="utf-8",
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
    """Dispatch payload to all configured hooks for this event. Never raises."""
    from .settings import load_settings

    settings = load_settings()
    hooks = settings.hooks.get(event.value, [])
    for cfg in hooks:
        if not cfg.enabled:
            continue
        outcome = run_hook(cfg, payload)
        if outcome.timed_out:
            print(
                f"\033[33m[Hook {cfg.command!r} timed out after {cfg.timeout_ms}ms]\033[0m",
                file=sys.stderr,
            )
        elif outcome.exit_code != 0:
            print(
                f"\033[33m[Hook {cfg.command!r} failed: exit {outcome.exit_code}]\033[0m",
                file=sys.stderr,
            )
            if outcome.stderr.strip():
                print(f"\033[33m{outcome.stderr.strip()}\033[0m", file=sys.stderr)
