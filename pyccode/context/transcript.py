"""JSONL transcript logging.

Leaf module in the context layer — only imports from pyccode.config.
The chain tracker ``_transcript_last_uuid`` lives here so it co-evolves
with the writer.
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

_transcript_last_uuid = None


def appendTranscript(role: str, content) -> None:
    """Append one entry to the session transcript JSONL file.

    Writes a single JSON object on its own line at ``TRANSCRIPT_PATH``.
    Updates the module-level ``_transcript_last_uuid`` to form a parent
    chain. Schema: ``type`` / ``uuid`` / ``parentUuid`` / ``timestamp`` /
    ``sessionId`` / ``cwd`` / ``version`` / ``message``.

    Open-write-close per entry for crash safety; no held file handle.
    Never raises: transcript failures print a yellow notice to stderr
    and return, so the chat loop is unaffected.
    """
    global _transcript_last_uuid
    try:
        entry_uuid = uuid.uuid4().hex
        entry = {
            "type": role,
            "uuid": entry_uuid,
            "parentUuid": _transcript_last_uuid,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "sessionId": SESSION_ID,
            "cwd": str(WORKDIR),
            "version": TRANSCRIPT_VERSION,
            "message": {"role": role, "content": content},
        }
        TRANSCRIPT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(TRANSCRIPT_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        _transcript_last_uuid = entry_uuid
    except Exception as e:
        print(f"\033[33m[Transcript write failed: {e}]\033[0m", file=sys.stderr)


def history_append(history: list, role: str, content) -> None:
    """Append a message to history and mirror it to the transcript."""
    history.append({"role": role, "content": content})
    appendTranscript(role, content)
