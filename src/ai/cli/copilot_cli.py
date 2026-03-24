"""Copilot CLI provider implementation."""

from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess
from typing import Optional

from ai.cli.cli_manager import CLIProvider

# Managed marker to identify Zen IDE's section in copilot-instructions.md
_ZEN_MARKER_START = "<!-- zen-ide-context-start -->"
_ZEN_MARKER_END = "<!-- zen-ide-context-end -->"
_COPILOT_INSTRUCTIONS_PATH = os.path.join(os.path.expanduser("~"), ".copilot", "copilot-instructions.md")


class CopilotCLI(CLIProvider):
    @property
    def id(self) -> str:
        return "copilot_cli"

    @property
    def display_name(self) -> str:
        return "Copilot"

    # --- binary discovery ---

    def find_binary(self) -> Optional[str]:
        nvm_dir = os.environ.get("NVM_DIR", os.path.expanduser("~/.nvm"))
        if os.path.isdir(nvm_dir):
            versions_dir = os.path.join(nvm_dir, "versions", "node")
            if os.path.isdir(versions_dir):
                try:
                    for v in sorted(os.listdir(versions_dir), reverse=True):
                        candidate = os.path.join(versions_dir, v, "bin", "copilot")
                        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                            return candidate
                except OSError:
                    pass

        for candidate in (
            os.path.expanduser("~/.local/bin/copilot"),
            "/usr/local/bin/copilot",
        ):
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate

        return shutil.which("copilot")

    # --- models ---

    def _fetch_models_impl(self, binary: str) -> list[str]:
        try:
            out = subprocess.run(
                [binary, "help", "config"],
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout
            in_model_section = False
            models: list[str] = []
            for line in out.splitlines():
                if re.match(r"\s*`model`", line):
                    in_model_section = True
                    continue
                if in_model_section:
                    m = re.match(r'\s*-\s*"([^"]+)"', line)
                    if m:
                        models.append(m.group(1))
                    elif line.strip() and not line.strip().startswith("-"):
                        break
            return models
        except Exception:
            pass
        return []

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
            argv.append(f"--resume={resume_session}")
        elif continue_last:
            argv.append("--continue")
        if yolo:
            argv.append("--yolo")
        if model:
            argv.extend(["--model", model])
        for d in extra_dirs or []:
            argv.extend(["--add-dir", d])
        return argv

    def append_ide_context(self, argv: list[str], editor_ctx: dict) -> None:
        if not editor_ctx:
            return
        from ai.cli.claude_cli import _build_ide_context_prompt
        from shared.ide_state_writer import get_state_file_path

        prompt = _build_ide_context_prompt(editor_ctx)
        _write_copilot_instructions(prompt)
        state_dir = os.path.dirname(get_state_file_path())
        argv.extend(["--add-dir", state_dir])

    # --- session management ---

    def sessions_dir(self, cwd: str | None = None) -> pathlib.Path | None:
        d = pathlib.Path.home() / ".copilot" / "session-state"
        return d if d.is_dir() else None

    def list_sessions(self, cwd: str | None = None) -> set[str]:
        d = self.sessions_dir(cwd)
        if not d:
            return set()
        return {p.name for p in d.iterdir() if p.is_dir()}

    def session_exists(self, session_id: str, cwd: str | None = None) -> bool:
        d = self.sessions_dir(cwd)
        return bool(d and (d / session_id).is_dir())

    # --- install instructions ---

    def install_lines(self) -> list[str]:
        RESET, DIM, CYAN, YELLOW = "\033[0m", "\033[2m", "\033[36m", "\033[33m"
        return [
            f"  {YELLOW}GitHub Copilot{RESET}",
            f"  {DIM}https://github.com/features/copilot/cli{RESET}",
            f"  {CYAN}curl -fsSL https://gh.io/copilot-install | bash{RESET}",
        ]


def _write_copilot_instructions(context_block: str) -> None:
    """Write/update the Zen IDE context section in Copilot's global instructions."""
    managed = f"{_ZEN_MARKER_START}\n{context_block}\n{_ZEN_MARKER_END}\n"

    try:
        existing = ""
        if os.path.isfile(_COPILOT_INSTRUCTIONS_PATH):
            with open(_COPILOT_INSTRUCTIONS_PATH, encoding="utf-8") as f:
                existing = f.read()

        if _ZEN_MARKER_START in existing:
            pattern = re.escape(_ZEN_MARKER_START) + r".*?" + re.escape(_ZEN_MARKER_END) + r"\n?"
            updated = re.sub(pattern, managed, existing, flags=re.DOTALL)
        else:
            separator = "\n" if existing and not existing.endswith("\n") else ""
            updated = existing + separator + managed

        os.makedirs(os.path.dirname(_COPILOT_INSTRUCTIONS_PATH), exist_ok=True)
        with open(_COPILOT_INSTRUCTIONS_PATH, "w", encoding="utf-8") as f:
            f.write(updated)
    except Exception:
        pass
