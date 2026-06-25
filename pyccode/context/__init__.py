"""Context management: transcript logging + four-layer size/count/token caps."""
from .transcript import appendTranscript, _history_append, _transcript_last_uuid
from .layers import (
    _persist_tool_result,
    maybePersistLargeToolResult,
    enforceToolResultBudget,
    microcompactMessages,
    _callCompactLLM,
    _buildCompactSummaryMessage,
    maybeAutoCompact,
)
