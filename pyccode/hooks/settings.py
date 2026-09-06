"""Settings loader: reads ~/.pyccode/settings.json once and caches."""
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .engine import HookConfig

SETTINGS_PATH = Path.home() / ".pyccode" / "settings.json"


@dataclass
class SettingsSchema:
    """Parsed settings.json. Hooks are keyed by event name."""
    hooks: dict[str, list[HookConfig]] = field(default_factory=dict)
    raw: dict = field(default_factory=dict)  # original JSON, forward-compat


_settings_cache: SettingsSchema | None = None


def load_settings(force_reload: bool = False) -> SettingsSchema:
    """Return cached settings. Reads file on first call (or force_reload).

    Missing file or malformed JSON → empty settings + stderr warning.
    Per-hook parse errors → skip that hook + stderr warning. Never raises.
    """
    global _settings_cache
    if _settings_cache is not None and not force_reload:
        return _settings_cache

    try:
        raw = (
            json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            if SETTINGS_PATH.exists()
            else {}
        )
    except Exception as e:
        print(f"\033[33m[Settings load failed: {e}]\033[0m", file=sys.stderr)
        raw = {}

    hooks_raw = raw.get("hooks", {}) or {}
    hooks: dict[str, list[HookConfig]] = {}
    for event_name, hook_list in hooks_raw.items():
        parsed: list[HookConfig] = []
        for h in hook_list or []:
            try:
                parsed.append(
                    HookConfig(
                        command=h["command"],
                        timeout_ms=int(h.get("timeout_ms", 5000)),
                        enabled=bool(h.get("enabled", True)),
                    )
                )
            except (KeyError, ValueError, TypeError) as e:
                print(
                    f"\033[33m[Settings: skipping malformed hook {h!r}: {e}]\033[0m",
                    file=sys.stderr,
                )
        hooks[event_name] = parsed

    _settings_cache = SettingsSchema(hooks=hooks, raw=raw)
    return _settings_cache
