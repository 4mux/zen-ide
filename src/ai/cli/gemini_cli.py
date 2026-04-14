"""Gemini CLI provider implementation."""

from __future__ import annotations

import os
import pathlib
import re
import shutil
from typing import Optional

from ai.cli.cli_provider import CLIProvider

# Managed marker to identify Zen IDE's section in GEMINI.md
_ZEN_MARKER_START = "<!-- zen-ide-context-start -->"
_ZEN_MARKER_END = "<!-- zen-ide-context-end -->"


class GeminiCLI(CLIProvider):
    @property
    def id(self) -> str:
        return "gemini_cli"

    @property
    def display_name(self) -> str:
        return "Gemini"

    # --- binary discovery ---

    def find_binary(self) -> Optional[str]:
        nvm_dir = os.environ.get("NVM_DIR", os.path.expanduser("~/.nvm"))
        if os.path.isdir(nvm_dir):
            versions_dir = os.path.join(nvm_dir, "versions", "node")
            if os.path.isdir(versions_dir):
                try:
                    for v in sorted(os.listdir(versions_dir), reverse=True):
                        candidate = os.path.join(versions_dir, v, "bin", "gemini")
                        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                            return candidate
                except OSError:
                    pass

        for candidate in (
            os.path.expanduser("~/.local/bin/gemini"),
            "/usr/local/bin/gemini",
        ):
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate

        return shutil.which("gemini")

    # --- models ---

    def _fetch_models_impl(self, binary: str) -> list[str]:
        return [
            "gemini-2.5-pro",
            "gemini-2.5-flash",
            "gemini-2.0-flash",
        ]

    # --- argv building ---

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
        argv = [binary]
        if resume_session:
            # Gemini uses index-based resume ("latest", or a number), not UUIDs.
            argv.extend(["--resume", "latest"])
        elif continue_last:
            argv.extend(["--resume", "latest"])
        if yolo:
            argv.append("--yolo")
        if model:
            argv.extend(["--model", model])
        for d in extra_dirs or []:
            argv.extend(["--include-directories", d])
        return argv

    def append_ide_context(self, argv: list[str], editor_ctx: dict) -> None:
        if not editor_ctx:
            return
        from ai.cli.claude_cli import _build_ide_context_prompt

        prompt = _build_ide_context_prompt(editor_ctx)
        cwd = os.getcwd()
        _write_gemini_instructions(cwd, prompt)

    # --- session management ---

    def sessions_dir(self, cwd: str | None = None) -> pathlib.Path | None:
        cwd = cwd or os.getcwd()
        # Gemini stores history per project name under ~/.gemini/history/<name>/
        history_root = pathlib.Path.home() / ".gemini" / "history"
        if not history_root.is_dir():
            return None
        # Find the project directory whose .project_root matches cwd
        try:
            for project_dir in history_root.iterdir():
                if not project_dir.is_dir():
                    continue
                root_file = project_dir / ".project_root"
                if root_file.is_file():
                    stored = root_file.read_text(encoding="utf-8").strip()
                    if os.path.abspath(stored) == os.path.abspath(cwd):
                        return project_dir
        except OSError:
            pass
        return None

    def list_sessions(self, cwd: str | None = None) -> set[str]:
        d = self.sessions_dir(cwd)
        if not d:
            return set()
        # Gemini session files are JSON files in the history directory
        return {p.stem for p in d.iterdir() if p.is_file() and p.suffix == ".json" and p.name != ".project_root"}

    def session_exists(self, session_id: str, cwd: str | None = None) -> bool:
        d = self.sessions_dir(cwd)
        if not d:
            return False
        return (d / f"{session_id}.json").is_file()

    # --- install instructions ---

    def install_lines(self) -> list[str]:
        RESET, DIM, CYAN, YELLOW = "\033[0m", "\033[2m", "\033[36m", "\033[33m"
        return [
            f"  {YELLOW}Gemini CLI{RESET}",
            f"  {DIM}https://github.com/google-gemini/gemini-cli{RESET}",
            f"  {CYAN}npm install -g @google/gemini-cli{RESET}",
        ]


def _write_gemini_instructions(cwd: str, context_block: str) -> None:
    """Write/update the Zen IDE context section in GEMINI.md at the project root."""
    gemini_md_path = os.path.join(cwd, "GEMINI.md")
    managed = f"{_ZEN_MARKER_START}\n{context_block}\n{_ZEN_MARKER_END}\n"

    try:
        existing = ""
        if os.path.isfile(gemini_md_path):
            with open(gemini_md_path, encoding="utf-8") as f:
                existing = f.read()

        if _ZEN_MARKER_START in existing:
            pattern = re.escape(_ZEN_MARKER_START) + r".*?" + re.escape(_ZEN_MARKER_END) + r"\n?"
            updated = re.sub(pattern, managed, existing, flags=re.DOTALL)
        else:
            separator = "\n" if existing and not existing.endswith("\n") else ""
            updated = existing + separator + managed

        with open(gemini_md_path, "w", encoding="utf-8") as f:
            f.write(updated)
    except Exception:
        pass
