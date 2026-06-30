"""Context management: transcript logging + four-layer size/count/token caps.

Public API: ``appendTranscript``, ``history_append`` (transcript);
``maybePersistLargeToolResult``, ``enforceToolResultBudget``,
``microcompactMessages``, ``maybeAutoCompact`` (layers). Private helpers
(``_persist_tool_result``, ``_callCompactLLM``, ``_buildCompactSummaryMessage``,
``_transcript_last_uuid``) stay inside their submodules — deep-import them
if you genuinely need them.
"""
from .transcript import appendTranscript, history_append
from .layers import (
    enforceToolResultBudget,
    maybeAutoCompact,
    maybePersistLargeToolResult,
    microcompactMessages,
)
