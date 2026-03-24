"""CLI Manager — abstract interface and registry for AI CLI providers.

Each provider (Claude, Copilot, …) implements the ``CLIProvider`` interface.
``CLIManager`` is the single entry point used by the rest of the IDE.
"""

from __future__ import annotations

import pathlib
import threading
from abc import ABC, abstractmethod
from typing import Optional

# Per-binary model cache: binary path → list of model strings.
# Only non-empty results are cached; empty results are retried on next call.
_model_cache: dict[str, list[str]] = {}


class CLIProvider(ABC):
    """Abstract interface that every AI CLI backend must implement."""

    # --- identity ---

    @property
    @abstractmethod
    def id(self) -> str:
        """Unique key, e.g. ``"claude_cli"``."""

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable name shown in UI, e.g. ``"Claude"``."""

    # --- binary discovery ---

    @abstractmethod
    def find_binary(self) -> Optional[str]:
        """Return the absolute path to the CLI binary, or ``None``."""

    # --- models ---

    def fetch_models(self, binary: str) -> list[str]:
        """Return available model names/aliases.  Results are cached."""
        if binary in _model_cache:
            return _model_cache[binary]
        models = self._fetch_models_impl(binary)
        if models:
            _model_cache[binary] = models
        return models

    @abstractmethod
    def _fetch_models_impl(self, binary: str) -> list[str]:
        """Provider-specific model discovery (no caching)."""

    # --- argv building ---

    @abstractmethod
    def build_argv(
        self,
        binary: str,
        *,
        resume_session: str | None = None,
        continue_last: bool = False,
        yolo: bool = False,
        model: str = "",
        extra_dirs: list[str] | None = None,
    ) -> list[str]:
        """Build the full argv list for spawning the CLI process."""

    @abstractmethod
    def append_ide_context(self, argv: list[str], editor_ctx: dict) -> None:
        """Append IDE context (system prompt, instructions file, etc.) to *argv*."""

    # --- session management ---

    @abstractmethod
    def sessions_dir(self, cwd: str | None = None) -> pathlib.Path | None:
        """Return the on-disk directory where sessions are stored, or ``None``."""

    @abstractmethod
    def list_sessions(self, cwd: str | None = None) -> set[str]:
        """Return the set of session IDs currently on disk."""

    @abstractmethod
    def session_exists(self, session_id: str, cwd: str | None = None) -> bool:
        """Return True if *session_id* can be found on disk."""

    # --- install instructions ---

    @abstractmethod
    def install_lines(self) -> list[str]:
        """Return ANSI-formatted lines with install instructions."""


class CLIManager:
    """Registry and façade — the single point of contact for the rest of the IDE."""

    def __init__(self) -> None:
        self._providers: dict[str, CLIProvider] = {}
        self._register_builtins()

    # --- registration ---

    def _register_builtins(self) -> None:
        from ai.cli.claude_cli import ClaudeCLI
        from ai.cli.copilot_cli import CopilotCLI

        for cls in (CopilotCLI, ClaudeCLI):
            p = cls()
            self._providers[p.id] = p

    def register(self, provider: CLIProvider) -> None:
        self._providers[provider.id] = provider

    # --- queries ---

    def get(self, provider_id: str) -> CLIProvider | None:
        return self._providers.get(provider_id)

    @property
    def provider_ids(self) -> list[str]:
        return list(self._providers)

    def labels(self) -> dict[str, str]:
        """Return {provider_id: display_name} for all registered providers."""
        return {p.id: p.display_name for p in self._providers.values()}

    def availability(self) -> dict[str, bool]:
        """Return {provider_id: is_installed} for all providers."""
        return {pid: p.find_binary() is not None for pid, p in self._providers.items()}

    def find_binary(self, provider_id: str) -> str | None:
        p = self._providers.get(provider_id)
        return p.find_binary() if p else None

    def fetch_models(self, provider_id: str) -> list[str]:
        p = self._providers.get(provider_id)
        if not p:
            return []
        binary = p.find_binary()
        if not binary:
            return []
        return p.fetch_models(binary)

    def prefetch_models(self, provider_id: str) -> None:
        """Fetch models in a background thread so they're cached early."""
        p = self._providers.get(provider_id)
        if not p:
            return
        binary = p.find_binary()
        if not binary or binary in _model_cache:
            return

        def _fetch():
            p.fetch_models(binary)

        threading.Thread(target=_fetch, daemon=True).start()

    # --- resolution ---

    def resolve(self, preferred: str = "") -> tuple[str | None, str | None]:
        """Return ``(binary, provider_id)`` for the best available CLI.

        Tries *preferred* first, then falls back through all registered
        providers in registration order.
        """
        if preferred and preferred in self._providers:
            binary = self._providers[preferred].find_binary()
            if binary:
                return binary, preferred

        for pid, p in self._providers.items():
            binary = p.find_binary()
            if binary:
                return binary, pid

        return None, None

    def resolve_label(self, preferred: str = "") -> str:
        """Return a display label for the best available provider."""
        _, pid = self.resolve(preferred)
        if pid:
            return self._providers[pid].display_name
        return "AI"

    def install_lines(self, provider_id: str | None = None) -> list[str]:
        """Return install instructions for one or all providers."""
        if provider_id:
            p = self._providers.get(provider_id)
            return p.install_lines() if p else []
        lines: list[str] = []
        for p in self._providers.values():
            if lines:
                lines.append("")
            lines.extend(p.install_lines())
        return lines


# Module-level singleton — imported everywhere.
cli_manager = CLIManager()
