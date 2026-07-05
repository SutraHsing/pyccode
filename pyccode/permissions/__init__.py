"""Permission layer: allowlist-based read-only command validator + tool-level gating.

Public API: ``CommandConfig``, ``READONLY_ALLOWLIST``, ``validate_command``,
``check_permission``, ``prompt_user``. Internal: ``_has_shell_operators``,
``_walk_flags``.
"""
from .engine import (
    ALLOWED_TOOLS,
    CommandConfig,
    check_permission,
    prompt_user,
    validate_command,
)
from .allowlist import READONLY_ALLOWLIST

__all__ = [
    "ALLOWED_TOOLS",
    "CommandConfig",
    "READONLY_ALLOWLIST",
    "check_permission",
    "prompt_user",
    "validate_command",
]
