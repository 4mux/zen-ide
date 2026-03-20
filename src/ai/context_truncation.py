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

The setting ``ai.context_truncation`` (default True) controls this.
"""

from __future__ import annotations

# How many messages at the tail of the conversation to keep in full.
# This must be large enough that the model sees the most recent tool
# call / result pairs.  12 ≈ 6 tool rounds.
_KEEP_RECENT = 12

# Conversation length threshold below which we skip truncation entirely.
# No point truncating a short conversation.
_MIN_MESSAGES_TO_TRUNCATE = 20

# Maximum characters to keep in a truncated tool result content.
_TRUNCATED_CONTENT_MAX_CHARS = 200

# Marker appended to truncated content so the model knows data was omitted.
_TRUNCATION_SUFFIX = "\n[...truncated for brevity]"


def truncate_conversation(
    messages: list[dict],
    *,
    keep_recent: int = _KEEP_RECENT,
    min_messages: int = _MIN_MESSAGES_TO_TRUNCATE,
    max_content_chars: int = _TRUNCATED_CONTENT_MAX_CHARS,
    format: str = "openai",  # "openai" or "anthropic"
) -> list[dict]:
    """Return a (possibly) truncated copy of *messages*.

    The returned list has the same length and message structure as the
    input, but middle tool-result messages have their ``content``
    shortened.  This preserves the conversation structure (required by
    the API) while dramatically reducing the token count of long
    agentic sessions.

    Args:
        messages: The full conversation messages list.
        keep_recent: Number of messages at the end to keep verbatim.
        min_messages: Don't truncate if the conversation is shorter.
        max_content_chars: Max chars to keep in a truncated tool result.
        format: "openai" (Copilot) or "anthropic" — determines how tool
                results are identified.

    Returns:
        A new list (shallow copy for kept messages, deep copy for
        truncated ones).
    """
    n = len(messages)
    if n < min_messages:
        return messages  # Short conversation, nothing to do

    # Determine the protected ranges:
    # - Index 0 is always the system prompt (keep)
    # - Index 1 is normally the first user message (keep)
    # - Last `keep_recent` messages (keep)
    #
    # Everything in between is the "truncation zone".
    protected_head = 2  # system + first user message
    protected_tail_start = max(protected_head, n - keep_recent)

    # If the truncation zone is empty, nothing to do
    if protected_tail_start <= protected_head:
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

    return result


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
