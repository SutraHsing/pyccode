"""Four-layer context management.

Layers 1 and 2 share ``_persist_tool_result`` (disk-write + preview
builder). Layer 3 clears old tool_result contents in place. Layer 4
LLM-summarizes the whole history when token count nears the context
window.
"""
import json
import os
import re
import sys

from pyccode.config import (
    AUTOCOMPACT_KEEP_RECENT,
    AUTOCOMPACT_MAX_OUTPUT_TOKENS,
    AUTOCOMPACT_PROMPT,
    AUTOCOMPACT_THRESHOLD,
    COMPACTABLE_TOOLS,
    LARGE_TOOL_RESULT_THRESHOLD,
    MICROCOMPACT_KEEP_RECENT,
    MICROCOMPACT_MAX_TOOL_RESULTS,
    OLD_TOOL_RESULT_PLACEHOLDER,
    SUMMARY_HEAD_CHARS,
    TOOL_RESULT_MESSAGE_BUDGET,
    TOOL_RESULTS_DIR,
    TRANSCRIPT_PATH,
    client,
)
from pyccode.context.transcript import history_append


def _persist_tool_result(tool_use_id: str, output: str) -> str:
    """Write ``output`` to disk and return a preview summary.

    Caller decides whether persistence is warranted (threshold or budget).
    Writes to ``TOOL_RESULTS_DIR / <safe_id>.<ext>`` with extension
    auto-sniffed via ``json.loads``. The returned summary uses the format
    documented on ``maybePersistLargeToolResult``.

    On filesystem failure, returns legacy 50K truncation with an error
    note appended so the chat loop never breaks.
    """
    try:
        try:
            json.loads(output)
            ext = "json"
        except (ValueError, TypeError):
            ext = "txt"

        safe_id = re.sub(r'[^A-Za-z0-9_-]', '_', tool_use_id)
        TOOL_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        file_path = TOOL_RESULTS_DIR / f"{safe_id}.{ext}"
        file_path.write_text(output, encoding='utf-8')

        summary = (
            f"[tool_result_persisted]\n"
            f"original_length: {len(output)} chars\n"
            f"persisted_to: {file_path}\n"
            f"\n--- HEAD ---\n"
            f"{output[:SUMMARY_HEAD_CHARS]}\n"
            f"--- end ---"
        )

        print(f"\033[33m[Tool result persisted: {len(output)} chars -> {file_path}]\033[0m")
        return summary
    except Exception as e:
        truncated = output[:LARGE_TOOL_RESULT_THRESHOLD]
        return truncated + f"\n[persist failed: {e}]"


def maybePersistLargeToolResult(tool_use_id: str, output: str) -> str:
    """Persist oversized tool output to a file and return a compact summary.

    If ``len(output) <= LARGE_TOOL_RESULT_THRESHOLD`` the input is returned
    unchanged. Otherwise the full output is written to
    ``TOOL_RESULTS_DIR / <safe_id>.<ext>`` and a head-only summary of
    ``SUMMARY_HEAD_CHARS`` chars plus small metadata is returned. The
    summary intentionally does not prescribe a downstream tool; the agent
    chooses how to inspect the file (read, grep, bash, etc.).

    On filesystem failure the function falls back to legacy truncation with
    an error note appended, so the chat loop never breaks due to persistence.

    Args:
        tool_use_id: The Anthropic tool_use ID; used as the filename stem.
        output: The full tool output string.

    Returns:
        Either the original ``output`` (under threshold) or a summary string
        referencing the persisted file path (over threshold).
    """
    if len(output) <= LARGE_TOOL_RESULT_THRESHOLD:
        return output
    return _persist_tool_result(tool_use_id, output)


def enforceToolResultBudget(results: list) -> list:
    """Cap total tool_result size in a single user message.

    If the combined ``len(content)`` across all ``tool_result`` blocks
    exceeds ``TOOL_RESULT_MESSAGE_BUDGET``, the largest results are
    persisted to disk (via ``_persist_tool_result``) and replaced with
    preview summaries until the total fits the budget. Already-small
    results (``<= 2 * SUMMARY_HEAD_CHARS``) are skipped because
    re-persisting would not shrink them.

    Runs after the per-result ``maybePersistLargeToolResult`` pass. The
    two compose: large individual results are summarized first, then the
    budget pass cleans up "many medium results" cases.

    Args:
        results: List of ``tool_result`` dicts (each with ``content`` and
            ``tool_use_id`` keys). Mutated in place via index assignment;
            the same list object is returned for convenience.

    Returns:
        The same ``results`` list, possibly with some entries' ``content``
        replaced by preview summaries.
    """
    total = sum(len(r["content"]) for r in results)
    if total <= TOOL_RESULT_MESSAGE_BUDGET:
        return results

    order = sorted(
        range(len(results)),
        key=lambda i: len(results[i]["content"]),
        reverse=True,
    )
    for i in order:
        if total <= TOOL_RESULT_MESSAGE_BUDGET:
            break
        content = results[i]["content"]
        if len(content) <= 2 * SUMMARY_HEAD_CHARS:
            break
        new_content = _persist_tool_result(results[i]["tool_use_id"], content)
        total += len(new_content) - len(content)
        results[i] = {**results[i], "content": new_content}
    return results


def microcompactMessages(history: list) -> list:
    """Clear old reproducible tool_result contents from conversation history.

    Triggered when the count of **uncleared compactable** ``tool_result``
    blocks exceeds ``MICROCOMPACT_MAX_TOOL_RESULTS``. Leaves the most
    recent ``MICROCOMPACT_KEEP_RECENT`` uncleared compactable blocks
    intact and replaces the older ones' ``content`` with
    ``OLD_TOOL_RESULT_PLACEHOLDER``.

    Compactable tools (``COMPACTABLE_TOOLS``) are those whose output the
    agent can reproduce by re-invoking the tool — file reads, bash, etc.
    ``run_subagent`` is excluded because sub-agent outputs are one-shot.

    Counts only uncleared blocks (content != placeholder), so compaction
    fires in batches roughly every ``MAX - KEEP_RECENT`` turns rather
    than every turn. This batches prefix-cache invalidation events.

    Runs once per turn before the API call in both ``chat()`` and
    ``handle_subagent()``. Mutates history in place. Never raises: any
    internal error returns history unchanged so the chat loop is
    unaffected.

    Args:
        history: Conversation history as a list of message dicts.

    Returns:
        The same ``history`` reference (mutated in place).
    """
    try:
        # tool_result blocks carry only tool_use_id; recover name from the matching tool_use.
        tool_use_index = {}
        for msg in history:
            if not isinstance(msg, dict) or msg.get("role") != "assistant":
                continue
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_use_index[block.get("id")] = block.get("name")

        uncleared_compactable = []
        for msg_idx, msg in enumerate(history):
            if not isinstance(msg, dict):
                continue
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for block_idx, block in enumerate(content):
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                if block.get("content") == OLD_TOOL_RESULT_PLACEHOLDER:
                    continue
                tool_name = tool_use_index.get(block.get("tool_use_id"))
                if tool_name in COMPACTABLE_TOOLS:
                    uncleared_compactable.append((msg_idx, block_idx))

        if len(uncleared_compactable) <= MICROCOMPACT_MAX_TOOL_RESULTS:
            return history

        to_compact = (
            uncleared_compactable[:-MICROCOMPACT_KEEP_RECENT]
            if MICROCOMPACT_KEEP_RECENT > 0
            else uncleared_compactable
        )
        for msg_idx, block_idx in to_compact:
            history[msg_idx]["content"][block_idx]["content"] = OLD_TOOL_RESULT_PLACEHOLDER

        return history
    except Exception:
        return history


def _callCompactLLM(history: list) -> str:
    """Send history to the model with the compact prompt; return summary text.

    No tools are passed, so the model can only return text. Uses the
    same model as the main agent (MODEL_NAME env). Lets exceptions
    propagate so maybeAutoCompact's try/except can apply its fallback.
    """
    response = client.messages.create(
        model=os.environ.get("MODEL_NAME", "claude-sonnet-4-5-20250929"),
        max_tokens=AUTOCOMPACT_MAX_OUTPUT_TOKENS,
        system="You are a helpful AI assistant tasked with summarizing conversations.",
        messages=history + [{"role": "user", "content": AUTOCOMPACT_PROMPT}],
    )
    return "".join(c.text for c in response.content if c.type == "text")


def _buildCompactSummaryMessage(summary: str) -> str:
    """Wrap the LLM-generated summary with the continuation prefix."""
    return (
        "This session is being continued from a previous conversation "
        "that ran out of context. A compact summary follows. Do not "
        "recap or ask the user what to do next — continue the work "
        "from where it left off.\n\n"
        f"If you need specific details from before compaction (exact "
        f"code snippets, error messages, content you generated), read "
        f"the full transcript at: {TRANSCRIPT_PATH}\n\n"
        "--- COMPACT SUMMARY ---\n"
        f"{summary.strip()}\n"
        "--- END SUMMARY ---"
    )


def maybeAutoCompact(history: list, last_input_tokens: int) -> bool:
    """Summarize and shrink history when the previous turn neared the context limit.

    Reactive trigger: caller passes ``last_input_tokens`` (set by
    ``chat()`` from ``response.usage.input_tokens`` after each API
    response). If it exceeds ``AUTOCOMPACT_THRESHOLD``, calls the model
    with a 9-section summary prompt and replaces history in place with
    ``[boundary_msg, summary_msg, *recent_N]``.

    Returns True if a compact happened, False otherwise. Never raises:
    on LLM failure or empty summary, prints a yellow notice to stderr
    and returns False without modifying history.

    Args:
        history: Conversation history as a list of message dicts.
            Mutated in place if a compact happens.
        last_input_tokens: Token count from the previous API response.
            ``chat()`` reads this off ``response.usage.input_tokens``.

    Returns:
        True if history was compacted, False otherwise.
    """
    if last_input_tokens <= AUTOCOMPACT_THRESHOLD:
        return False
    if len(history) < AUTOCOMPACT_KEEP_RECENT + 2:
        return False

    try:
        summary = _callCompactLLM(history)
    except Exception as e:
        print(f"\033[33m[Auto-compact failed: {e}]\033[0m", file=sys.stderr)
        return False

    if not summary or not summary.strip():
        print("\033[33m[Auto-compact failed: empty summary]\033[0m", file=sys.stderr)
        return False

    recent = history[-AUTOCOMPACT_KEEP_RECENT:]
    history.clear()
    history_append(history, "user", "[compact_boundary]")
    history_append(history, "user", _buildCompactSummaryMessage(summary))
    for msg in recent:
        history.append(msg)  # already in transcript; don't re-append

    print(f"\033[33m[Auto-compact: history reduced to {len(history)} messages]\033[0m")
    return True
