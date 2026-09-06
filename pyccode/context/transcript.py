"""JSONL transcript logging.

Context-layer module — imports from pyccode.config and pyccode.hooks.engine
(never the reverse; hooks.engine does not import context, so no cycle).
The chain tracker ``_transcript_last_uuid`` lives here so it co-evolves
with the writer.

Transcript writing is an internal hook on ``MessageAppend``: importing
this module registers it (single registration site at the bottom).
``history_append`` fires the event; the hook writes the entry — same
incremental timing as v1, now routed through hook dispatch.
"""
import json
import sys
import uuid
from datetime import datetime, timezone

from pyccode.config import (
    SESSION_ID,
    TRANSCRIPT_PATH,
    TRANSCRIPT_VERSION,
    WORKDIR,
)
from pyccode.hooks.engine import HookType, register_internal_hook, run_hooks

_transcript_last_uuid = None


def _read_git_branch() -> str | None:
    """Parse .git/HEAD for the branch name. No subprocess.

    Returns None when not a git repo, detached HEAD, or a worktree
    (worktrees have a .git *file* whose content has no ref: line for us).
    Read fresh per entry — the agent may ``git checkout`` mid-session.
    """
    try:
        text = (WORKDIR / ".git" / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if text.startswith("ref: refs/heads/"):
        return text[len("ref: refs/heads/"):]
    return None


def appendTranscript(role: str, content, usage: dict | None = None) -> None:
    """Append one entry to the session transcript JSONL file.

    Writes a single JSON object on its own line at ``TRANSCRIPT_PATH``.
    Updates the module-level ``_transcript_last_uuid`` to form a parent
    chain. Schema: ``type`` / ``uuid`` / ``parentUuid`` / ``timestamp`` /
    ``sessionId`` / ``cwd`` / ``gitBranch`` / ``version`` / ``message``.
    Assistant entries embed ``message.usage`` when provided (Claude Code
    parity for token accounting).

    Open-write-close per entry for crash safety; no held file handle.
    Never raises: transcript failures print a yellow notice to stderr
    and return, so the chat loop is unaffected.
    """
    global _transcript_last_uuid
    try:
        entry_uuid = uuid.uuid4().hex
        message: dict = {"role": role, "content": content}
        if role == "assistant" and usage is not None:
            message["usage"] = usage
        entry = {
            "type": role,
            "uuid": entry_uuid,
            "parentUuid": _transcript_last_uuid,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "sessionId": SESSION_ID,
            "cwd": str(WORKDIR),
            "gitBranch": _read_git_branch(),
            "version": TRANSCRIPT_VERSION,
            "message": message,
        }
        TRANSCRIPT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(TRANSCRIPT_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        _transcript_last_uuid = entry_uuid
    except Exception as e:
        print(f"\033[33m[Transcript write failed: {e}]\033[0m", file=sys.stderr)


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


def _transcript_message_append_hook(payload: dict) -> None:
    """Internal MessageAppend hook: one transcript entry per history append."""
    appendTranscript(payload["role"], payload["content"], usage=payload.get("usage"))


register_internal_hook(HookType.MESSAGE_APPEND, _transcript_message_append_hook)
