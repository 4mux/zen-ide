"""
Direct HTTP client for GitHub Copilot completions API.

Bypasses the Copilot CLI (Node.js) for ~5x faster completions:
- CLI: ~6s (1.5s Node.js startup + 4.5s API round-trip)
- Direct API: ~1s (with cached token)

Authentication flow:
1. Read OAuth token from ~/.config/github-copilot/apps.json
2. Exchange it for a short-lived session token via GitHub API
3. Use session token for completion requests
"""

import json
import os
import threading
import time
import urllib.request
from typing import Callable, Optional

_COPILOT_APPS_PATH = os.path.expanduser("~/.config/github-copilot/apps.json")
_TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"
_COMPLETIONS_URL = "https://api.githubcopilot.com/chat/completions"
_FIM_COMPLETIONS_URL = "https://api.githubcopilot.com/v1/completions"

# Editor identity headers — must match a recognised Copilot integration
# so the billing backend applies standard subscription pricing.
_EDITOR_VERSION = "vscode/1.100.0"
_PLUGIN_VERSION = "copilot/1.250.0"
_USER_AGENT = "GithubCopilot/1.250.0"

# System message for FIM-style code completion
_SYSTEM_PROMPT = (
    "You are a code completion engine embedded in a code editor. "
    "The user will show code with a █ cursor marker. "
    "Output ONLY the code that should be inserted at █. "
    "Rules:\n"
    "- Output raw code ONLY — no markdown, no explanation, no commentary\n"
    "- Never describe, review, or discuss the code\n"
    "- Never output sentences in natural language\n"
    "- If █ is inside a comment, complete the comment text naturally\n"
    "- If █ is on a blank line, output the next logical line(s) of code\n"
    "- Do NOT repeat code that already exists before or after █\n"
    "- Output NOTHING if there is no meaningful completion"
)

# Refresh token 60s before expiry
_TOKEN_REFRESH_MARGIN_S = 60


class CopilotAPI:
    """Direct HTTP client for GitHub Copilot completions."""

    # Class-level state shared across all instances (all tabs).
    # Avoids re-trying a failing FIM endpoint and re-exchanging tokens
    # every time a new tab opens.
    _shared_lock = threading.Lock()
    _shared_oauth_token: Optional[str] = None
    _shared_session_token: Optional[str] = None
    _shared_token_expires_at: float = 0
    _shared_api_base_url: Optional[str] = None
    _shared_fim_available: Optional[bool] = None

    def __init__(self):
        pass

    def is_available(self) -> bool:
        """Check if Copilot API credentials exist."""
        return self._get_oauth_token() is not None

    @property
    def _fim_available(self):
        return CopilotAPI._shared_fim_available

    @_fim_available.setter
    def _fim_available(self, value):
        CopilotAPI._shared_fim_available = value

    @property
    def _api_base_url(self):
        return CopilotAPI._shared_api_base_url

    @_api_base_url.setter
    def _api_base_url(self, value):
        CopilotAPI._shared_api_base_url = value

    def complete(
        self,
        prompt: str,
        model: str = "gpt-4.1-mini",
        max_tokens: int = 500,
        timeout: float = 15,
    ) -> Optional[str]:
        """Request a completion from the Copilot API.

        Returns the completion text, or None on error.
        Thread-safe — meant to be called from a background thread.
        """
        results = self._complete_chat_raw(prompt, model, max_tokens, timeout, n=1)
        return results[0] if results else None

    def complete_multi(
        self,
        prompt: str,
        model: str = "gpt-4.1-mini",
        max_tokens: int = 500,
        timeout: float = 15,
        n: int = 3,
    ) -> list[str]:
        """Request multiple chat completions for suggestion cycling.

        Returns up to n alternative completions. Empty list on error.
        """
        return self._complete_chat_raw(prompt, model, max_tokens, timeout, n=n)

    def _complete_chat_raw(
        self,
        prompt: str,
        model: str,
        max_tokens: int,
        timeout: float,
        n: int = 1,
    ) -> list[str]:
        """Internal: request n chat completions, returning all choices."""
        token = self._get_session_token()
        if not token:
            return []

        payload = json.dumps(
            {
                "model": model,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": max_tokens,
                "temperature": 0.1 if n == 1 else 0.3,
                "n": n,
                "stream": False,
            }
        ).encode()

        req = urllib.request.Request(
            _COMPLETIONS_URL,
            data=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "User-Agent": _USER_AGENT,
                "Editor-Version": _EDITOR_VERSION,
                "Editor-Plugin-Version": _PLUGIN_VERSION,
                "Copilot-Integration-Id": "copilot",
                "openai-intent": "copilot-ghost",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                result = json.loads(resp.read())
                choices = result.get("choices", [])
                if choices:
                    texts = []
                    for choice in choices:
                        content = choice.get("message", {}).get("content", "")
                        if content:
                            texts.append(content)
                    return texts
        except urllib.error.HTTPError as e:
            if e.code == 401:
                with CopilotAPI._shared_lock:
                    CopilotAPI._shared_session_token = None
                    CopilotAPI._shared_token_expires_at = 0
        except Exception:
            pass

        return []

    def complete_fim(
        self,
        prefix: str,
        suffix: str,
        language: str = "",
        file_path: str = "",
        max_tokens: int = 500,
        timeout: float = 10,
    ) -> Optional[str]:
        """Request a FIM (fill-in-middle) completion using the completions endpoint.

        Uses FIM (fill-in-middle) with separate prefix/suffix params
        sent to a completions endpoint optimized for inline code completion.
        Returns the completion text, or None on error.
        """
        results = self._complete_fim_raw(prefix, suffix, language, file_path, max_tokens, timeout, n=1)
        return results[0] if results else None

    def complete_fim_multi(
        self,
        prefix: str,
        suffix: str,
        language: str = "",
        file_path: str = "",
        max_tokens: int = 500,
        timeout: float = 10,
        n: int = 3,
    ) -> list[str]:
        """Request multiple FIM completions for suggestion cycling.

        Returns up to n alternative completions. Empty list on error.
        """
        return self._complete_fim_raw(prefix, suffix, language, file_path, max_tokens, timeout, n=n)

    def _complete_fim_raw(
        self,
        prefix: str,
        suffix: str,
        language: str,
        file_path: str,
        max_tokens: int,
        timeout: float,
        n: int = 1,
    ) -> list[str]:
        """Internal: request n FIM completions, returning all choices."""
        if self._fim_available is False:
            return []

        token = self._get_session_token()
        if not token:
            return []

        fim_url = self._api_base_url + "/v1/completions" if self._api_base_url else _FIM_COMPLETIONS_URL

        payload = json.dumps(
            {
                "prompt": prefix,
                "suffix": suffix,
                "max_tokens": max_tokens,
                "temperature": 0 if n == 1 else 0.2,
                "top_p": 1,
                "n": n,
            }
        ).encode()

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": _USER_AGENT,
            "Editor-Version": _EDITOR_VERSION,
            "Editor-Plugin-Version": _PLUGIN_VERSION,
            "Copilot-Integration-Id": "copilot",
            "openai-intent": "copilot-ghost",
        }
        if language:
            headers["X-Copilot-Language"] = language
        if file_path:
            headers["X-Copilot-Filename"] = file_path

        req = urllib.request.Request(fim_url, data=payload, headers=headers)

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                result = json.loads(resp.read())
                choices = result.get("choices", [])
                if choices:
                    self._fim_available = True
                    texts = [c.get("text", "") for c in choices]
                    texts = [t for t in texts if t]
                    return texts
        except urllib.error.HTTPError as e:
            if e.code == 401:
                with CopilotAPI._shared_lock:
                    CopilotAPI._shared_session_token = None
                    CopilotAPI._shared_token_expires_at = 0
            elif e.code in (404, 403):
                self._fim_available = False
        except Exception:
            pass

        return []

    def complete_stream(
        self,
        prompt: str,
        model: str = "gpt-4.1-mini",
        max_tokens: int = 500,
        timeout: float = 15,
        on_chunk: Callable[[str], None] | None = None,
        on_done: Callable[[], None] | None = None,
    ) -> str | None:
        """Stream a completion, calling on_chunk(text) for each token.

        on_chunk and on_done are scheduled on the GTK main thread via GLib.idle_add.
        Returns the full assembled text, or None on error.
        """
        from gi.repository import GLib

        token = self._get_session_token()
        if not token:
            return None

        payload = json.dumps(
            {
                "model": model,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": max_tokens,
                "temperature": 0.1,
                "stream": True,
            }
        ).encode()

        req = urllib.request.Request(
            _COMPLETIONS_URL,
            data=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "User-Agent": _USER_AGENT,
                "Editor-Version": _EDITOR_VERSION,
                "Editor-Plugin-Version": _PLUGIN_VERSION,
                "Copilot-Integration-Id": "copilot",
                "openai-intent": "copilot-ghost",
            },
        )

        full_text: list[str] = []
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                for raw_line in resp:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                        delta = data.get("choices", [{}])[0].get("delta", {})
                        chunk = delta.get("content", "")
                        if chunk:
                            full_text.append(chunk)
                            if on_chunk:
                                GLib.idle_add(on_chunk, chunk)
                    except (json.JSONDecodeError, IndexError, KeyError):
                        continue

            if on_done:
                GLib.idle_add(on_done)

            result = "".join(full_text)
            return result if result else None

        except urllib.error.HTTPError as e:
            if e.code == 401:
                with CopilotAPI._shared_lock:
                    CopilotAPI._shared_session_token = None
                    CopilotAPI._shared_token_expires_at = 0
        except Exception:
            pass

        return None

    def _get_oauth_token(self) -> Optional[str]:
        """Read the Copilot OAuth token from the local config file."""
        if CopilotAPI._shared_oauth_token:
            return CopilotAPI._shared_oauth_token

        if not os.path.isfile(_COPILOT_APPS_PATH):
            return None

        try:
            with open(_COPILOT_APPS_PATH) as f:
                apps = json.load(f)

            for app in apps.values():
                if isinstance(app, dict) and "oauth_token" in app:
                    CopilotAPI._shared_oauth_token = app["oauth_token"]
                    return CopilotAPI._shared_oauth_token
        except Exception:
            pass

        return None

    def _get_session_token(self) -> Optional[str]:
        """Get a valid Copilot session token, refreshing if expired."""
        with CopilotAPI._shared_lock:
            if (
                CopilotAPI._shared_session_token
                and time.time() < CopilotAPI._shared_token_expires_at - _TOKEN_REFRESH_MARGIN_S
            ):
                return CopilotAPI._shared_session_token

        oauth = self._get_oauth_token()
        if not oauth:
            return None

        req = urllib.request.Request(
            _TOKEN_URL,
            headers={
                "Authorization": f"token {oauth}",
                "Accept": "application/json",
                "User-Agent": _USER_AGENT,
                "Editor-Version": _EDITOR_VERSION,
                "Editor-Plugin-Version": _PLUGIN_VERSION,
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())

            with CopilotAPI._shared_lock:
                CopilotAPI._shared_session_token = data["token"]
                CopilotAPI._shared_token_expires_at = float(data["expires_at"])
                # Store API base URL from endpoints if available
                endpoints = data.get("endpoints", {})
                if "api" in endpoints:
                    CopilotAPI._shared_api_base_url = endpoints["api"].rstrip("/")
                return CopilotAPI._shared_session_token
        except Exception:
            pass

        return None
