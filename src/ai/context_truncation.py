"""Context truncation for AI chat tool-use conversations.

When an agentic tool-use loop runs for many rounds, the conversation
sent to the API grows with every round (assistant + tool results).
By round 50 the context might contain 100+ messages, each re-sent in
full on every API call — costing tokens quadratically.

This module provides a ``truncate_conversation`` helper that both
CopilotHTTPProvider and AnthropicHTTPProvider call before sending
the messages list.  The strategy:

1. Always keep the **system message** (index 0) unchanged.
2. Always keep the **first user message** (the original task).
3. Always keep the **last N messages** unchanged (recent context
   the model needs to continue coherently).
4. For messages in the "middle" zone: truncate tool-result content
   to a short summary so the model still sees the call/result
   structure but doesn't pay for kilobytes of old file listings.
5. If the serialised conversation exceeds ``max_total_chars``,
   progressively drop the oldest middle messages until it fits.

Settings:
- ``ai.context_truncation`` (default True) — enables truncation.
- ``ai.max_context_chars`` (default 500000) — hard cap on total
  serialised conversation size in characters (~125K tokens).
"""

from __future__ import annotations

# How many messages at the tail of the conversation to keep in full.
# This must be large enough that the model sees the most recent tool
# call / result pairs.  8 ≈ 4 tool rounds.
_KEEP_RECENT = 8

# Conversation length threshold below which we skip truncation entirely.
# With a 30k tokens/min rate limit, even short conversations with large
# tool results can blow through the budget by round 5-6.
_MIN_MESSAGES_TO_TRUNCATE = 8

# Maximum characters to keep in a truncated tool result content.
_TRUNCATED_CONTENT_MAX_CHARS = 200

# Default hard cap on total serialised conversation size (chars).
# ~500K chars ≈ ~125K tokens — a safe ceiling for most models.
_DEFAULT_MAX_TOTAL_CHARS = 500_000

# Marker appended to truncated content so the model knows data was omitted.
_TRUNCATION_SUFFIX = "\n[...truncated for brevity]"


def _estimate_message_chars(msg: dict) -> int:
    """Rough character count for a single message dict."""
    content = msg.get("content", "")
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        total = 0
        for block in content:
            if isinstance(block, dict):
                total += len(str(block.get("content", "")))
                total += len(str(block.get("text", "")))
                total += len(str(block.get("thinking", "")))
                total += len(str(block.get("input", "")))
            elif isinstance(block, str):
                total += len(block)
        return total
    return len(str(content))


def truncate_conversation(
    messages: list[dict],
    *,
    keep_recent: int = _KEEP_RECENT,
    min_messages: int = _MIN_MESSAGES_TO_TRUNCATE,
    max_content_chars: int = _TRUNCATED_CONTENT_MAX_CHARS,
    max_total_chars: int = _DEFAULT_MAX_TOTAL_CHARS,
    format: str = "openai",  # "openai" or "anthropic"
) -> list[dict]:
    """Return a (possibly) truncated copy of *messages*.

    The returned list has the same length and message structure as the
    input, but middle tool-result messages have their ``content``
    shortened.  This preserves the conversation structure (required by
    the API) while dramatically reducing the token count of long
    agentic sessions.

    If the conversation still exceeds *max_total_chars* after content
    truncation, the oldest messages in the middle zone are dropped
    entirely (replaced with a single summary placeholder) until the
    conversation fits.

    Args:
        messages: The full conversation messages list.
        keep_recent: Number of messages at the end to keep verbatim.
        min_messages: Don't truncate if the conversation is shorter.
        max_content_chars: Max chars to keep in a truncated tool result.
        max_total_chars: Hard cap on total serialised conversation size.
        format: "openai" (Copilot) or "anthropic" — determines how tool
                results are identified.

    Returns:
        A new list (shallow copy for kept messages, deep copy for
        truncated ones).
    """
    n = len(messages)
    if n < min_messages:
        # Even short conversations should respect the hard size cap.
        if max_total_chars > 0 and _total_chars(messages) > max_total_chars:
            return _enforce_size_cap(messages, max_total_chars, keep_recent, format)
        return messages

    # Determine the protected ranges:
    # - Index 0 is always the system prompt (keep)
    # - Index 1 is normally the first user message (keep)
    # - Last `keep_recent` messages (keep)
    #
    # Everything in between is the "truncation zone".
    protected_head = 2  # system + first user message
    protected_tail_start = max(protected_head, n - keep_recent)

    # If the truncation zone is empty, nothing to do (except size cap)
    if protected_tail_start <= protected_head:
        if max_total_chars > 0 and _total_chars(messages) > max_total_chars:
            return _enforce_size_cap(messages, max_total_chars, keep_recent, format)
        return messages

    result: list[dict] = []
    for i, msg in enumerate(messages):
        if i < protected_head or i >= protected_tail_start:
            # Protected — keep as-is
            result.append(msg)
        else:
            # Truncation zone — shorten tool result content
            truncated = _maybe_truncate_message(msg, max_content_chars, format)
            result.append(truncated)

    # Enforce hard size cap — drop oldest middle messages if still too large
    if max_total_chars > 0 and _total_chars(result) > max_total_chars:
        result = _enforce_size_cap(result, max_total_chars, keep_recent, format)

    return result


def _total_chars(messages: list[dict]) -> int:
    """Estimate total serialised character count of a messages list."""
    return sum(_estimate_message_chars(m) for m in messages)


def _enforce_size_cap(
    messages: list[dict],
    max_total_chars: int,
    keep_recent: int,
    format: str,
) -> list[dict]:
    """Drop oldest middle messages until total size fits under the cap.

    Preserves the first 2 messages (system + first user) and the last
    *keep_recent* messages.  Inserts a placeholder so the model knows
    messages were omitted.
    """
    n = len(messages)
    protected_head = min(2, n)
    protected_tail_start = max(protected_head, n - keep_recent)

    head = messages[:protected_head]
    tail = messages[protected_tail_start:]
    middle = messages[protected_head:protected_tail_start]

    # Drop from the oldest end of the middle until we fit
    placeholder = {
        "role": "user" if format == "anthropic" else "system",
        "content": "[Earlier conversation history was truncated to stay within context limits]",
    }

    while middle and _total_chars(head + [placeholder] + middle + tail) > max_total_chars:
        middle.pop(0)

    if len(middle) < (protected_tail_start - protected_head):
        # We dropped something — insert placeholder
        return head + [placeholder] + middle + tail
    return head + middle + tail


def _maybe_truncate_message(
    msg: dict,
    max_chars: int,
    format: str,
) -> dict:
    """Truncate a single message's content if it's a tool result.

    Returns the original message unchanged if it's not a tool result
    or if it's already short enough.
    """
    role = msg.get("role", "")

    if format == "openai":
        # OpenAI/Copilot: tool results have role="tool"
        if role != "tool":
            return msg
        content = msg.get("content", "")
        if isinstance(content, str) and len(content) > max_chars:
            return {
                **msg,
                "content": content[:max_chars] + _TRUNCATION_SUFFIX,
            }
        return msg

    elif format == "anthropic":
        # Anthropic: tool results are in role="user" messages with
        # content blocks of type "tool_result"
        if role != "user":
            return msg
        content = msg.get("content")
        if not isinstance(content, list):
            return msg

        # Check if any blocks are tool_result type
        has_tool_result = any(isinstance(block, dict) and block.get("type") == "tool_result" for block in content)
        if not has_tool_result:
            return msg

        # Truncate tool_result block contents
        new_content = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                block_content = block.get("content", "")
                if isinstance(block_content, str) and len(block_content) > max_chars:
                    new_content.append(
                        {
                            **block,
                            "content": block_content[:max_chars] + _TRUNCATION_SUFFIX,
                        }
                    )
                else:
                    new_content.append(block)
            else:
                new_content.append(block)

        return {**msg, "content": new_content}

    return msg
