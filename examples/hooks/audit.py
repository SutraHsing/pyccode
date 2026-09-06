#!/usr/bin/env python3
"""Example PostToolUse hook: append-only audit log.

Reads the PostToolUse payload from stdin, writes one JSON line per
tool call to ~/.pyccode/audit.jsonl. Useful for "what did the agent
run this session?" inspection, cost/size tracking, and debugging.

Wire it up by adding to ~/.pyccode/settings.json:

    {
      "hooks": {
        "PostToolUse": [
          {
            "command": "python3 examples/hooks/audit.py",
            "timeout_ms": 5000
          }
        ]
      }
    }

Exit codes:
    0 — log line appended successfully
    1 — payload parse failure or disk write failure
"""
import json
import sys
from pathlib import Path

LOG_PATH = Path.home() / ".pyccode" / "audit.jsonl"


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read())
    except Exception as e:
        print(f"audit hook: bad payload: {e}", file=sys.stderr)
        return 1

    entry = {
        "timestamp": payload.get("timestamp"),
        "session_id": payload.get("session_id"),
        "agent_id": payload.get("agent_id"),
        "tool_name": payload.get("tool_name"),
        "tool_use_id": payload.get("tool_use_id"),
        "tool_error": payload.get("tool_error", False),
        "input_size": len(json.dumps(payload.get("tool_input", {}), ensure_ascii=False)),
        "response_size": len(payload.get("tool_response", "") or ""),
        "response_preview": (payload.get("tool_response", "") or "")[:200],
    }

    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"audit hook: write failed: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
