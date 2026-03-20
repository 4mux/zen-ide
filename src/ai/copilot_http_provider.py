"""
Copilot HTTP Provider for Zen IDE.

Direct HTTP streaming to the GitHub Copilot Chat API.
Uses the same OpenAI-compatible endpoint as the inline completion system
but with the full chat streaming interface and tool use support.

Authentication flow:
1. Read GitHub token from GITHUB_TOKEN env var or ~/.zen_ide/api_keys.json
2. Fall back to OAuth token from ~/.config/github-copilot/apps.json
3. Exchange token for a short-lived Copilot session token
4. Use session token for chat completion requests

OAuth device flow:
When no token is available, users can authenticate via GitHub's OAuth
device flow — no browser redirect needed, just enter a code at github.com.
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
_SOCKET_READ_TIMEOUT_S = 30

_API_KEYS_PATH = Path.home() / ".zen_ide" / "api_keys.json"
_COPILOT_APPS_PATH = Path.home() / ".config" / "github-copilot" / "apps.json"
_TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"
_COMPLETIONS_URL = "https://api.githubcopilot.com/chat/completions"
_MODELS_URL = "https://api.githubcopilot.com/models"
_USER_AGENT = "ZenIDE/1.0"

# GitHub OAuth device flow endpoints
_DEVICE_CODE_URL = "https://github.com/login/device/code"
_OAUTH_TOKEN_URL = "https://github.com/login/oauth/access_token"
# Well-known Copilot OAuth client ID (shared across editors)
_COPILOT_CLIENT_ID = "Iv1.b507a08c87ecfe98"

_TOKEN_REFRESH_MARGIN_S = 60

_THINKING_MARKER = "\u200b"
_CONTENT_MARKER = "\u200c"

_KNOWN_MODELS: list[str] = []

_DEFAULT_MODEL = "claude-sonnet-4.6"


def _load_github_tokens() -> list[str]:
    """Load all candidate GitHub tokens, ordered by reliability for Copilot.

    Copilot's own OAuth token (from apps.json) is the most reliable source
    since it's guaranteed to have Copilot scope. GITHUB_TOKEN env var is
    often a regular PAT without Copilot access, so it's tried last.
    """
    tokens: list[str] = []

    # 1. Copilot OAuth token (most reliable — always has Copilot scope)
    try:
        if _COPILOT_APPS_PATH.is_file():
            apps = json.loads(_COPILOT_APPS_PATH.read_text(encoding="utf-8"))
            for app in apps.values():
                if isinstance(app, dict) and "oauth_token" in app:
                    tokens.append(app["oauth_token"])
                    break
    except Exception:
        pass

    # 2. ~/.zen_ide/api_keys.json → {"github": "ghp_..."}
    try:
        if _API_KEYS_PATH.exists():
            data = json.loads(_API_KEYS_PATH.read_text(encoding="utf-8"))
            token = data.get("github") or None
            if token and token not in tokens:
                tokens.append(token)
    except Exception:
        pass

    # 3. GITHUB_TOKEN env var (often a regular PAT without Copilot scope)
    # Only use if it looks like a Copilot OAuth token (gho_ prefix)
    token = os.environ.get("GITHUB_TOKEN")
    if token and token not in tokens and token.startswith("gho_"):
        tokens.append(token)

    return tokens


def _has_copilot_oauth_token() -> bool:
    """Check if we have a known-good Copilot OAuth token.

    Returns True only if we have a token from apps.json (Copilot OAuth flow)
    or a gho_ prefixed token (Copilot OAuth tokens). Regular GitHub PATs
    (ghp_) are not reliable for Copilot.
    """
    # Check apps.json first (most reliable)
    try:
        if _COPILOT_APPS_PATH.is_file():
            apps = json.loads(_COPILOT_APPS_PATH.read_text(encoding="utf-8"))
            for app in apps.values():
                if isinstance(app, dict) and "oauth_token" in app:
                    return True
    except Exception:
        pass

    # Check api_keys.json for a gho_ token
    try:
        if _API_KEYS_PATH.exists():
            data = json.loads(_API_KEYS_PATH.read_text(encoding="utf-8"))
            token = data.get("github") or ""
            if token.startswith("gho_"):
                return True
    except Exception:
        pass

    # Check env var for gho_ token
    token = os.environ.get("GITHUB_TOKEN", "")
    if token.startswith("gho_"):
        return True

    return False


def _save_oauth_token(oauth_token: str):
    """Save an OAuth token to ~/.config/github-copilot/apps.json."""
    _COPILOT_APPS_PATH.parent.mkdir(parents=True, exist_ok=True)
    apps = {}
    try:
        if _COPILOT_APPS_PATH.is_file():
            apps = json.loads(_COPILOT_APPS_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    apps["github.com"] = {"oauth_token": oauth_token}
    _COPILOT_APPS_PATH.write_text(json.dumps(apps, indent=2) + "\n", encoding="utf-8")


class CopilotHTTPProvider:
    """Direct HTTP provider for the GitHub Copilot Chat API."""

    DEFAULT_MODEL = _DEFAULT_MODEL

    # Class-level shared state for session token caching
    _shared_lock = threading.Lock()
    _shared_session_token: Optional[str] = None
    _shared_token_expires_at: float = 0
    _shared_api_base_url: Optional[str] = None
    _cached_models: Optional[list] = None
    _models_fetched: bool = False
    # Prevent multiple concurrent token refreshes causing a stampede
    _token_refresh_lock = threading.Lock()
    # How long to allow a streaming connection to be idle (no data) before aborting
    _IDLE_STREAM_TIMEOUT_S = 300

    def __init__(self):
        self._stop_requested = False
        self._current_response: Optional[urllib.request.addinfourl] = None
        self._last_error: Optional[str] = None
        # Tool use state
        self._tool_calls: list[dict] = []
        self._tool_call_accumulators: dict[int, dict] = {}
        self._text_response = ""
        self._pending_finish_reason: Optional[str] = None
        # Conversation tracking for tool use continuations
        self._conversation: list[dict] = []
        self._model: str = _DEFAULT_MODEL
        self._system_prompt: Optional[str] = None
        self._tools: Optional[list] = None
        self._max_tokens: int = 16384

    @property
    def is_available(self) -> bool:
        """Check if Copilot is available with a known-good token.

        We only return True if we have a Copilot OAuth token (from apps.json
        or gho_ prefix). Regular GitHub PATs (ghp_) often lack Copilot scope
        and would fail at runtime, so we don't count them as "available".
        """
        return _has_copilot_oauth_token()

    def get_available_models(self) -> list:
        """Return available models, fetching from API if possible."""
        if CopilotHTTPProvider._models_fetched and CopilotHTTPProvider._cached_models:
            return CopilotHTTPProvider._cached_models.copy()

        token = self._get_session_token()
        if not token:
            return _KNOWN_MODELS.copy()

        try:
            req = urllib.request.Request(
                _MODELS_URL,
                headers={
                    "Authorization": f"Bearer {token}",
                    "User-Agent": _USER_AGENT,
                    "Editor-Version": _USER_AGENT,
                    "Copilot-Integration-Id": "vscode-chat",
                },
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                models = []
                for m in data.get("data", data) if isinstance(data, dict) else data:
                    if not isinstance(m, dict):
                        continue
                    model_id = m.get("id", "")
                    # Only include models marked for the model picker
                    if model_id and m.get("model_picker_enabled", False):
                        models.append(model_id)
                if models:
                    # Sort by category priority: powerful first, then versatile, then lightweight
                    category_order = {"powerful": 0, "versatile": 1, "lightweight": 2}
                    model_categories = {}
                    for m in data.get("data", data) if isinstance(data, dict) else data:
                        if isinstance(m, dict):
                            mid = m.get("id", "")
                            cat = m.get("model_picker_category", "")
                            model_categories[mid] = category_order.get(cat, 3)
                    models.sort(key=lambda mid: (model_categories.get(mid, 3), mid))
                    CopilotHTTPProvider._cached_models = models
                    CopilotHTTPProvider._models_fetched = True
                    return models.copy()
        except Exception:
            pass

        return _KNOWN_MODELS.copy()

    # ------------------------------------------------------------------
    # OAuth device flow
    # ------------------------------------------------------------------

    @staticmethod
    def start_device_flow() -> Optional[dict]:
        """Start GitHub OAuth device flow for Copilot authentication.

        Returns dict with keys: device_code, user_code, verification_uri, interval
        or None on failure.
        """
        try:
            body = json.dumps({"client_id": _COPILOT_CLIENT_ID, "scope": "copilot"}).encode()
            req = urllib.request.Request(
                _DEVICE_CODE_URL,
                data=body,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return {
                    "device_code": data["device_code"],
                    "user_code": data["user_code"],
                    "verification_uri": data.get("verification_uri", "https://github.com/login/device"),
                    "interval": data.get("interval", 5),
                    "expires_in": data.get("expires_in", 900),
                }
        except Exception:
            return None

    @staticmethod
    def poll_device_flow(device_code: str) -> tuple[Optional[str], str, int]:
        """Poll for OAuth token completion.

        Returns (token, status, new_interval) where status is one of:
        - "complete" — token is the OAuth access token
        - "pending" — user hasn't completed auth yet
        - "slow_down" — polling too fast, use new_interval
        - "expired" — device code expired
        - "error" — unexpected error

        new_interval is the suggested polling interval in seconds (default 5).
        """
        try:
            body = json.dumps(
                {
                    "client_id": _COPILOT_CLIENT_ID,
                    "device_code": device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                }
            ).encode()
            req = urllib.request.Request(
                _OAUTH_TOKEN_URL,
                data=body,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            if "access_token" in data:
                token = data["access_token"]
                _save_oauth_token(token)
                # Clear cached session token so it gets re-exchanged
                with CopilotHTTPProvider._shared_lock:
                    CopilotHTTPProvider._shared_session_token = None
                    CopilotHTTPProvider._shared_token_expires_at = 0
                return token, "complete", 5

            error = data.get("error", "")
            new_interval = data.get("interval", 5)

            if error == "authorization_pending":
                return None, "pending", new_interval
            if error == "slow_down":
                # GitHub wants us to slow down — return specific status with new interval
                return None, "slow_down", new_interval
            if error == "expired_token":
                return None, "expired", 5
            if error == "":
                # Empty error but no token — treat as pending
                return None, "pending", new_interval
            return None, "error", 5
        except Exception:
            return None, "error", 5

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------

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

        Uses the same callback interface as Anthropic/OpenAI HTTP providers.
        Callbacks are called from background thread — caller must schedule
        to main thread via GLib.idle_add().
        """
        tokens = _load_github_tokens()
        if not tokens:
            if on_error:
                on_error(
                    "GitHub token not configured. Set GITHUB_TOKEN env var, "
                    "add to ~/.zen_ide/api_keys.json, or use the Sign in with GitHub option."
                )
            return

        self._stop_requested = False
        self._model = model or self.DEFAULT_MODEL
        self._system_prompt = system_prompt
        self._tools = tools
        self._max_tokens = max_tokens
        self._tool_calls = []
        self._tool_call_accumulators = {}
        self._text_response = ""
        self._pending_finish_reason = None
        self._conversation = list(messages)

        self._stream_request(on_chunk, on_complete, on_error, on_tool_use)

    def continue_with_tool_results(
        self,
        tool_results: list[dict],
        on_chunk: Optional[Callable[[str], None]] = None,
        on_complete: Optional[Callable[[str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
        on_tool_use: Optional[Callable[[list, str], None]] = None,
    ):
        """Continue conversation after tool execution.

        Args:
            tool_results: List of {"tool_call_id": str, "content": str} dicts.
        """
        # Build assistant message with tool_calls
        assistant_msg = {"role": "assistant", "content": self._text_response or None}
        if self._tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {"name": tc["name"], "arguments": json.dumps(tc["input"])},
                }
                for tc in self._tool_calls
            ]
        self._conversation.append(assistant_msg)

        # Add tool result messages
        for tr in tool_results:
            self._conversation.append(
                {
                    "role": "tool",
                    "tool_call_id": tr["tool_call_id"],
                    "content": tr["content"],
                }
            )

        # Reset tool state
        self._tool_calls = []
        self._tool_call_accumulators = {}
        self._text_response = ""
        self._pending_finish_reason = None

        self._stream_request(on_chunk, on_complete, on_error, on_tool_use)

    def _stream_request(self, on_chunk, on_complete, on_error, on_tool_use):
        """Execute a streaming API request in a background thread."""
        from shared.ai_debug_log import ai_log

        def run():
            t0 = time.monotonic()
            stream_error_type = ""
            ai_log.request(
                "copilot",
                self._model,
                msg_count=len(self._conversation),
                has_tools=bool(self._tools),
                max_tokens=self._max_tokens,
            )
            try:
                session_token = self._get_session_token()
                if not session_token:
                    detail = self._last_error or "unknown error"
                    ai_log.error(f"session token failure: {detail}", provider="copilot")
                    if on_error:
                        on_error(f"Failed to get Copilot session token: {detail}")
                    return

                # Apply context truncation to reduce token cost in long
                # agentic sessions.  Old tool results in the middle of the
                # conversation are shortened while the recent context and
                # the original user message are kept intact.
                conversation = self._conversation
                try:
                    from shared.settings.settings_manager import get_setting

                    if get_setting("ai.context_truncation", True):
                        from ai.context_truncation import truncate_conversation

                        conversation = truncate_conversation(self._conversation, format="openai")
                except Exception:
                    pass  # Truncation failure must never block the request

                api_messages = []
                if self._system_prompt:
                    api_messages.append({"role": "system", "content": self._system_prompt})
                api_messages.extend(conversation)

                body = {
                    "model": self._model,
                    "max_tokens": self._max_tokens,
                    "stream": True,
                    "messages": api_messages,
                }

                if self._tools:
                    body["tools"] = self._tools

                base_url = CopilotHTTPProvider._shared_api_base_url or "https://api.githubcopilot.com"
                url = f"{base_url}/chat/completions"

                req_data = json.dumps(body).encode("utf-8")
                req = urllib.request.Request(
                    url,
                    data=req_data,
                    headers={
                        "Authorization": f"Bearer {session_token}",
                        "Content-Type": "application/json",
                        "Accept": "text/event-stream",
                        "User-Agent": _USER_AGENT,
                        "Editor-Version": _USER_AGENT,
                        "Copilot-Integration-Id": "vscode-chat",
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
                finish_reason = None
                last_activity = time.monotonic()

                while True:
                    if self._stop_requested:
                        break

                    try:
                        raw_line = self._current_response.readline()
                    except socket.timeout:
                        # Socket read timed out — check idle timeout and stop flag
                        if self._stop_requested:
                            break
                        if time.monotonic() - last_activity > CopilotHTTPProvider._IDLE_STREAM_TIMEOUT_S:
                            stream_error_type = "idle_timeout"
                            ai_log.event("stream_idle_timeout", "copilot: no data for idle timeout")
                            break
                        continue  # Keep waiting for data
                    except OSError as e:
                        stream_error_type = f"OSError: {e}"
                        ai_log.event("stream_oserror", f"copilot: {e}")
                        break

                    if not raw_line:
                        # End of stream
                        break

                    # We received data — update last activity timestamp
                    last_activity = time.monotonic()

                    line = raw_line.decode("utf-8", errors="replace")
                    buffer += line

                    while "\n" in buffer:
                        sse_line, buffer = buffer.split("\n", 1)
                        result = self._parse_sse_line(sse_line)
                        if result is None:
                            continue
                        if isinstance(result, str):
                            clean = result.lstrip(_CONTENT_MARKER).lstrip(_THINKING_MARKER)
                            if not result.startswith(_THINKING_MARKER):
                                self._text_response += clean
                            if on_chunk:
                                on_chunk(result)
                        elif isinstance(result, dict):
                            if result.get("_finish_reason"):
                                finish_reason = result["_finish_reason"]

                self._current_response = None
                duration = time.monotonic() - t0

                if self._stop_requested:
                    ai_log.event("stream_stopped", "copilot: user cancelled")
                    return

                # Pick up any pending finish_reason that was deferred because
                # content and finish_reason arrived in the same SSE event.
                if finish_reason is None and hasattr(self, "_pending_finish_reason") and self._pending_finish_reason:
                    finish_reason = self._pending_finish_reason
                    self._pending_finish_reason = None

                # Finalize accumulated tool calls
                if self._tool_call_accumulators:
                    for idx in sorted(self._tool_call_accumulators):
                        acc = self._tool_call_accumulators[idx]
                        try:
                            inp = json.loads(acc.get("arguments", "{}"))
                        except json.JSONDecodeError:
                            inp = {}
                        self._tool_calls.append(
                            {
                                "id": acc.get("id", ""),
                                "name": acc.get("name", ""),
                                "input": inp,
                            }
                        )

                # Detect abnormal stream end: no finish_reason + empty response
                if not finish_reason and not self._text_response.strip() and not self._tool_calls:
                    error_detail = stream_error_type or "stream ended with no data"
                    ai_log.stream_end(
                        "copilot",
                        stop_reason="",
                        response_len=0,
                        duration_s=duration,
                        error_type=error_detail,
                    )
                    if on_error:
                        on_error(f"Connection lost — server stopped responding ({error_detail})")
                    return

                ai_log.stream_end(
                    "copilot",
                    stop_reason=finish_reason or "end_of_stream",
                    response_len=len(self._text_response),
                    duration_s=duration,
                )

                if finish_reason == "tool_calls" and self._tool_calls and on_tool_use:
                    on_tool_use(self._tool_calls, self._text_response)
                elif on_complete:
                    text = self._text_response
                    on_complete(text)

            except urllib.error.HTTPError as e:
                self._current_response = None
                error_body = ""
                try:
                    error_body = e.read().decode("utf-8", errors="replace")
                    error_data = json.loads(error_body)
                    error_msg = error_data.get("error", {}).get("message", error_body)
                except Exception:
                    error_msg = error_body or str(e)

                if e.code == 401:
                    with CopilotHTTPProvider._shared_lock:
                        CopilotHTTPProvider._shared_session_token = None
                        CopilotHTTPProvider._shared_token_expires_at = 0
                    error_msg = f"Copilot authentication failed. {error_msg}"
                elif e.code == 403:
                    error_msg = f"Copilot access denied. Your GitHub account may not have Copilot enabled. {error_msg}"
                elif e.code == 429:
                    error_msg = f"Rate limited. {error_msg}"

                ai_log.error(error_msg, provider="copilot", http_status=e.code)
                if on_error:
                    on_error(error_msg)
            except Exception as e:
                self._current_response = None
                ai_log.error(str(e), provider="copilot")
                if not self._stop_requested and on_error:
                    on_error(str(e))

        thread = threading.Thread(target=run, daemon=True)
        thread.start()

    def _parse_sse_line(self, line: str):
        """Parse a single SSE line (OpenAI-compatible format).

        Returns:
            str: Text chunk (with marker prefix).
            dict: Control signal (e.g. {"_finish_reason": "tool_calls"}).
            None: No actionable data.
        """
        line = line.rstrip("\r\n")

        if not line.startswith("data: "):
            # If there's a pending finish_reason from a previous content+finish event,
            # return it now (any non-data line is a good opportunity).
            pfr = getattr(self, "_pending_finish_reason", None)
            if pfr:
                self._pending_finish_reason = None
                return {"_finish_reason": pfr}
            return None

        json_str = line[6:]
        if json_str.strip() == "[DONE]":
            return None
        if not json_str.strip():
            return None

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            return None

        choices = data.get("choices", [])
        if not choices:
            return None

        choice = choices[0]
        delta = choice.get("delta", {})

        # Process content/tool calls first, before checking finish_reason.
        # Some API responses include both content and finish_reason in the
        # same event — checking finish_reason first would drop that content.
        content = delta.get("content", "")

        # Accumulate tool calls (side-effect only, no return value)
        tool_calls = delta.get("tool_calls", [])
        for tc in tool_calls:
            idx = tc.get("index", 0)
            if idx not in self._tool_call_accumulators:
                self._tool_call_accumulators[idx] = {
                    "id": "",
                    "name": "",
                    "arguments": "",
                }
            acc = self._tool_call_accumulators[idx]
            if tc.get("id"):
                acc["id"] = tc["id"]
            fn = tc.get("function", {})
            if fn.get("name"):
                acc["name"] = fn["name"]
            if fn.get("arguments"):
                acc["arguments"] += fn["arguments"]

        # If there's content, return it. The finish_reason (if any) will be
        # stored as a pending signal and returned on the next call, ensuring
        # no content is dropped.
        if content:
            # Stash finish_reason for the next _parse_sse_line call
            fr = choice.get("finish_reason")
            if fr:
                self._pending_finish_reason = fr
            return f"{_CONTENT_MARKER}{content}"

        # Check finish reason (only when no content to return)
        fr = choice.get("finish_reason")
        if fr:
            return {"_finish_reason": fr}

        return None

    def _get_session_token(self) -> Optional[str]:
        """Get a valid Copilot session token, refreshing if expired.

        Tries each candidate GitHub token in order until one succeeds.
        Copilot's OAuth token is tried first (most reliable).
        """
        with CopilotHTTPProvider._shared_lock:
            if (
                CopilotHTTPProvider._shared_session_token
                and time.time() < CopilotHTTPProvider._shared_token_expires_at - _TOKEN_REFRESH_MARGIN_S
            ):
                return CopilotHTTPProvider._shared_session_token

        # Prevent many threads from simultaneously trying to refresh the session
        # token (stampede). One thread performs the exchange while others wait.
        with CopilotHTTPProvider._token_refresh_lock:
            # Re-check cached token after acquiring refresh lock (another thread
            # may have refreshed while we were waiting).
            with CopilotHTTPProvider._shared_lock:
                if (
                    CopilotHTTPProvider._shared_session_token
                    and time.time() < CopilotHTTPProvider._shared_token_expires_at - _TOKEN_REFRESH_MARGIN_S
                ):
                    return CopilotHTTPProvider._shared_session_token

            tokens = _load_github_tokens()
            if not tokens:
                self._last_error = "No GitHub token found"
                return None

            last_error = None
            for github_token in tokens:
                req = urllib.request.Request(
                    _TOKEN_URL,
                    headers={
                        "Authorization": f"token {github_token}",
                        "Accept": "application/json",
                        "User-Agent": _USER_AGENT,
                    },
                )

                try:
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        data = json.loads(resp.read())

                    with CopilotHTTPProvider._shared_lock:
                        CopilotHTTPProvider._shared_session_token = data["token"]
                        CopilotHTTPProvider._shared_token_expires_at = float(data["expires_at"])
                        endpoints = data.get("endpoints", {})
                        if "api" in endpoints:
                            CopilotHTTPProvider._shared_api_base_url = endpoints["api"].rstrip("/")
                        return CopilotHTTPProvider._shared_session_token
                except urllib.error.HTTPError as e:
                    last_error = f"HTTP {e.code}: {e.reason}"
                except Exception as e:
                    last_error = str(e)

            # If we failed to obtain a token, avoid hammering the token endpoint
            # by setting a short cooldown before the next refresh attempt.
            cooldown = 5
            with CopilotHTTPProvider._shared_lock:
                CopilotHTTPProvider._shared_session_token = None
                CopilotHTTPProvider._shared_token_expires_at = time.time() + cooldown

            self._last_error = last_error
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
