"""
Anthropic HTTP Provider for Zen IDE.

Direct HTTP streaming to the Anthropic Messages API.
Supports streaming responses with thinking blocks (extended thinking)
and tool use for agentic coding.

API key resolution order:
1. Environment variable ANTHROPIC_API_KEY
2. ~/.zen_ide/api_keys.json → {"anthropic": "sk-ant-..."}
"""

import json
import os
import socket
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Optional

# Read timeout for individual socket reads (seconds).
# This prevents the stream from hanging forever if the server stops sending data.
# The watchdog in ai_chat_terminal.py will cancel after _STALE_REQUEST_TIMEOUT_S (90s)
# but this timeout ensures the blocking read eventually returns so the thread can check
# _stop_requested and exit cleanly.
_SOCKET_READ_TIMEOUT_S = 30

_API_KEYS_PATH = Path.home() / ".zen_ide" / "api_keys.json"
_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
_MODELS_URL = "https://api.anthropic.com/v1/models"
_API_VERSION = "2023-06-01"
_THINKING_MARKER = "\u200b"
_CONTENT_MARKER = "\u200c"

_KNOWN_MODELS: list[str] = []

_DEFAULT_MODEL = "claude-sonnet-4-20250514"


def _load_api_key() -> Optional[str]:
    """Load Anthropic API key from env or config file."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    try:
        if _API_KEYS_PATH.exists():
            data = json.loads(_API_KEYS_PATH.read_text(encoding="utf-8"))
            return data.get("anthropic") or None
    except Exception:
        pass
    return None


class AnthropicHTTPProvider:
    """Direct HTTP provider for the Anthropic Messages API."""

    DEFAULT_MODEL = _DEFAULT_MODEL

    _cached_models: Optional[list] = None
    _models_fetched: bool = False

    def __init__(self):
        self._stop_requested = False
        self._current_response: Optional[urllib.request.addinfourl] = None
        # Tool use state
        self._tool_calls: list[dict] = []
        self._current_tool_call: Optional[dict] = None
        self._current_tool_input_json = ""
        self._text_response = ""
        # Conversation tracking for tool use continuations
        self._conversation: list[dict] = []
        self._model: str = _DEFAULT_MODEL
        self._system_prompt: Optional[str] = None
        self._tools: Optional[list] = None
        self._max_tokens: int = 16384

    @property
    def is_available(self) -> bool:
        return _load_api_key() is not None

    def get_available_models(self) -> list:
        """Return available models, fetching from API if possible."""
        if AnthropicHTTPProvider._models_fetched and AnthropicHTTPProvider._cached_models:
            return AnthropicHTTPProvider._cached_models.copy()

        api_key = _load_api_key()
        if not api_key:
            return _KNOWN_MODELS.copy()

        try:
            req = urllib.request.Request(
                _MODELS_URL,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": _API_VERSION,
                },
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                models = []
                for m in data.get("data", []):
                    model_id = m.get("id", "")
                    if model_id:
                        models.append(model_id)
                if models:
                    models.sort()
                    AnthropicHTTPProvider._cached_models = models
                    AnthropicHTTPProvider._models_fetched = True
                    return models.copy()
        except Exception:
            pass

        return _KNOWN_MODELS.copy()

    def send_message_stream(
        self,
        messages: list[dict],
        model: str = None,
        system_prompt: str = None,
        tools: Optional[list] = None,
        on_chunk: Optional[Callable[[str], None]] = None,
        on_complete: Optional[Callable[[str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
        on_tool_use: Optional[Callable[[list, str], None]] = None,
        max_tokens: int = 16384,
    ):
        """Send messages and stream the response in a background thread.

        Args:
            messages: List of {"role": "user"/"assistant", "content": "..."} dicts.
            model: Model ID (e.g. "claude-sonnet-4-20250514").
            system_prompt: Optional system prompt.
            tools: Optional list of tool definitions (Anthropic format).
            on_chunk: Called with each text chunk (prefixed with thinking/content markers).
            on_complete: Called with the full response text when done (no tool use).
            on_error: Called with error message on failure.
            on_tool_use: Called with (tool_calls, text_response) when model requests tool use.
            max_tokens: Maximum tokens in the response.
        """
        api_key = _load_api_key()
        if not api_key:
            if on_error:
                on_error(
                    "Anthropic API key not configured. Set ANTHROPIC_API_KEY env var or add to ~/.zen_ide/api_keys.json"
                )
            return

        self._stop_requested = False
        self._model = model or self.DEFAULT_MODEL
        self._system_prompt = system_prompt
        self._tools = tools
        self._max_tokens = max_tokens
        self._tool_calls = []
        self._current_tool_call = None
        self._current_tool_input_json = ""
        self._text_response = ""
        self._conversation = list(messages)

        self._stream_request(api_key, messages, on_chunk, on_complete, on_error, on_tool_use)

    def continue_with_tool_results(
        self,
        tool_results: list[dict],
        on_chunk: Optional[Callable[[str], None]] = None,
        on_complete: Optional[Callable[[str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
        on_tool_use: Optional[Callable[[list, str], None]] = None,
    ):
        """Continue conversation after tool execution.

        Appends the assistant's tool_use response and the user's tool_results
        to the conversation, then streams the next response.

        Args:
            tool_results: List of {"tool_use_id": str, "content": str} dicts.
            on_chunk/on_complete/on_error/on_tool_use: Same as send_message_stream.
        """
        api_key = _load_api_key()
        if not api_key:
            if on_error:
                on_error("Anthropic API key not configured")
            return

        # Build assistant message with content blocks (text + tool_use)
        assistant_content = []
        if self._text_response.strip():
            assistant_content.append({"type": "text", "text": self._text_response})
        for tc in self._tool_calls:
            assistant_content.append(
                {
                    "type": "tool_use",
                    "id": tc["id"],
                    "name": tc["name"],
                    "input": tc["input"],
                }
            )
        self._conversation.append({"role": "assistant", "content": assistant_content})

        # Build user message with tool_result blocks
        result_content = []
        for tr in tool_results:
            result_content.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tr["tool_use_id"],
                    "content": tr["content"],
                }
            )
        self._conversation.append({"role": "user", "content": result_content})

        # Reset tool state for next round
        self._tool_calls = []
        self._current_tool_call = None
        self._current_tool_input_json = ""
        self._text_response = ""

        # Apply context truncation to reduce token cost in long
        # agentic sessions.
        send_messages = self._conversation
        try:
            from shared.settings.settings_manager import get_setting

            if get_setting("ai.context_truncation", True):
                from ai.context_truncation import truncate_conversation

                send_messages = truncate_conversation(self._conversation, format="anthropic")
        except Exception:
            pass  # Truncation failure must never block the request

        self._stream_request(api_key, send_messages, on_chunk, on_complete, on_error, on_tool_use)

    def _stream_request(
        self,
        api_key: str,
        messages: list[dict],
        on_chunk,
        on_complete,
        on_error,
        on_tool_use,
    ):
        """Execute a streaming API request in a background thread."""
        from shared.ai_debug_log import ai_log

        def run():
            t0 = time.monotonic()
            stream_error_type = ""
            ai_log.request(
                "anthropic",
                self._model,
                msg_count=len(messages),
                has_tools=bool(self._tools),
                max_tokens=self._max_tokens,
            )
            try:
                body = {
                    "model": self._model,
                    "max_tokens": self._max_tokens,
                    "stream": True,
                    "messages": messages,
                }

                if self._system_prompt:
                    body["system"] = self._system_prompt

                if self._tools:
                    body["tools"] = self._tools

                # Enable extended thinking for supported models
                if "opus" in self._model or "sonnet" in self._model:
                    body["thinking"] = {
                        "type": "enabled",
                        "budget_tokens": min(self._max_tokens, 10000),
                    }

                req_data = json.dumps(body).encode("utf-8")
                req = urllib.request.Request(
                    _MESSAGES_URL,
                    data=req_data,
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": _API_VERSION,
                        "content-type": "application/json",
                        "accept": "text/event-stream",
                    },
                    method="POST",
                )

                self._current_response = urllib.request.urlopen(req, timeout=300)

                # Set socket-level read timeout to prevent blocking forever.
                # The urlopen timeout only covers the connection handshake.
                # This ensures individual read() calls will time out, allowing
                # the loop to check _stop_requested periodically.
                try:
                    sock = self._current_response.fp.raw._sock
                    sock.settimeout(_SOCKET_READ_TIMEOUT_S)
                except Exception:
                    pass  # Socket access may fail on some platforms; continue anyway

                buffer = ""
                stop_reason = None

                while True:
                    if self._stop_requested:
                        break

                    try:
                        raw_line = self._current_response.readline()
                    except socket.timeout:
                        # Socket read timed out — check if we should stop
                        if self._stop_requested:
                            break
                        continue  # Keep waiting for data
                    except OSError as e:
                        stream_error_type = f"OSError: {e}"
                        ai_log.event("stream_oserror", f"anthropic: {e}")
                        break

                    if not raw_line:
                        # End of stream
                        break

                    line = raw_line.decode("utf-8", errors="replace")
                    buffer += line

                    while "\n" in buffer:
                        sse_line, buffer = buffer.split("\n", 1)
                        result = self._parse_sse_line(sse_line)
                        if result is None:
                            continue
                        if isinstance(result, str):
                            # Text or thinking chunk
                            clean = result.lstrip(_THINKING_MARKER).lstrip(_CONTENT_MARKER)
                            if not result.startswith(_THINKING_MARKER):
                                self._text_response += clean
                            if on_chunk:
                                on_chunk(result)
                        elif isinstance(result, dict):
                            if result.get("_stop_reason"):
                                stop_reason = result["_stop_reason"]

                self._current_response = None
                duration = time.monotonic() - t0

                if self._stop_requested:
                    ai_log.event("stream_stopped", "anthropic: user cancelled")
                    return

                # Detect abnormal stream end: no stop_reason + empty response
                if not stop_reason and not self._text_response.strip() and not self._tool_calls:
                    error_detail = stream_error_type or "stream ended with no data"
                    ai_log.stream_end(
                        "anthropic",
                        stop_reason="",
                        response_len=0,
                        duration_s=duration,
                        error_type=error_detail,
                    )
                    if on_error:
                        on_error(f"Connection lost — server stopped responding ({error_detail})")
                    return

                ai_log.stream_end(
                    "anthropic",
                    stop_reason=stop_reason or "end_of_stream",
                    response_len=len(self._text_response),
                    duration_s=duration,
                )

                if stop_reason == "tool_use" and self._tool_calls and on_tool_use:
                    on_tool_use(self._tool_calls, self._text_response)
                elif on_complete:
                    on_complete(self._text_response)

            except urllib.error.HTTPError as e:
                self._current_response = None
                duration = time.monotonic() - t0
                error_body = ""
                try:
                    error_body = e.read().decode("utf-8", errors="replace")
                    error_data = json.loads(error_body)
                    error_msg = error_data.get("error", {}).get("message", error_body)
                except Exception:
                    error_msg = error_body or str(e)

                if e.code == 401:
                    error_msg = f"Invalid Anthropic API key. {error_msg}"
                elif e.code == 429:
                    error_msg = f"Rate limited. {error_msg}"
                elif e.code == 529:
                    error_msg = f"Anthropic API overloaded. {error_msg}"

                ai_log.error(error_msg, provider="anthropic", http_status=e.code)
                if on_error:
                    on_error(error_msg)
            except Exception as e:
                self._current_response = None
                ai_log.error(str(e), provider="anthropic")
                if not self._stop_requested and on_error:
                    on_error(str(e))

        thread = threading.Thread(target=run, daemon=True)
        thread.start()

    def _parse_sse_line(self, line: str):
        """Parse a single SSE line from the Anthropic streaming response.

        Returns:
            str: Text/thinking chunk (with marker prefix).
            dict: Control signal (e.g. {"_stop_reason": "tool_use"}).
            None: No actionable data.
        """
        line = line.rstrip("\r\n")

        if not line.startswith("data: "):
            return None

        json_str = line[6:]
        if not json_str.strip():
            return None

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            return None

        event_type = data.get("type", "")

        if event_type == "content_block_start":
            block = data.get("content_block", {})
            if block.get("type") == "tool_use":
                self._current_tool_call = {
                    "id": block.get("id", ""),
                    "name": block.get("name", ""),
                    "input": {},
                }
                self._current_tool_input_json = ""
            return None

        if event_type == "content_block_delta":
            delta = data.get("delta", {})
            delta_type = delta.get("type", "")

            if delta_type == "text_delta":
                text = delta.get("text", "")
                return f"{_CONTENT_MARKER}{text}" if text else None

            if delta_type == "thinking_delta":
                thinking = delta.get("thinking", "")
                return f"{_THINKING_MARKER}{thinking}" if thinking else None

            if delta_type == "input_json_delta":
                self._current_tool_input_json += delta.get("partial_json", "")
                return None

        if event_type == "content_block_stop":
            if self._current_tool_call is not None:
                # Parse accumulated JSON input
                try:
                    self._current_tool_call["input"] = (
                        json.loads(self._current_tool_input_json) if self._current_tool_input_json else {}
                    )
                except json.JSONDecodeError:
                    self._current_tool_call["input"] = {}
                self._tool_calls.append(self._current_tool_call)
                self._current_tool_call = None
                self._current_tool_input_json = ""
            return None

        if event_type == "message_delta":
            stop_reason = data.get("delta", {}).get("stop_reason", "")
            if stop_reason:
                return {"_stop_reason": stop_reason}

        if event_type == "error":
            error_msg = data.get("error", {}).get("message", "Unknown error")
            return f"{_CONTENT_MARKER}\n[Error: {error_msg}]\n"

        return None

    def stop(self):
        """Stop the current streaming request."""
        self._stop_requested = True
        if self._current_response:
            try:
                self._current_response.close()
            except Exception:
                pass
            self._current_response = None
