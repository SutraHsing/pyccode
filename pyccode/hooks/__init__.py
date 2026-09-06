"""Hook framework: subprocess-based event hooks. MVP: PostToolUse only.

Public API: ``HookType``, ``HookConfig``, ``HookOutcome``, ``run_hook``,
``run_hooks``, ``build_post_tool_use_payload``, ``load_settings``,
``SettingsSchema``, ``SETTINGS_PATH``.
"""
from .engine import (
    HookConfig,
    HookOutcome,
    HookType,
    build_post_tool_use_payload,
    run_hook,
    run_hooks,
)
from .settings import SETTINGS_PATH, SettingsSchema, load_settings

__all__ = [
    "HookConfig",
    "HookOutcome",
    "HookType",
    "SETTINGS_PATH",
    "SettingsSchema",
    "build_post_tool_use_payload",
    "load_settings",
    "run_hook",
    "run_hooks",
]
