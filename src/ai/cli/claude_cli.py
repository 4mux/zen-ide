"""Claude CLI provider implementation."""

from __future__ import annotations

import os
import pathlib
import shutil
from typing import Optional

from ai.cli.cli_manager import CLIProvider


class ClaudeCLI(CLIProvider):

    @property
    def id(self) -> str:
        return "claude_cli"

    @property
    def display_name(self) -> str:
        return "Claude"

    # --- binary discovery ---

    def find_binary(self) -> Optional[str]:
        for candidate in (
            os.path.expanduser("~/.local/bin/claude"),
            "/usr/local/bin/claude",
        ):
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
        return shutil.which("claude")

    # --- models ---

    def _fetch_models_impl(self, binary: str) -> list[str]:
        # Hardcoded because Anthropic has no free/unauthenticated API to list models.
        # Valid values: aliases ("opus", "sonnet", "haiku") or full names ("claude-opus-4-6").
        # Update manually from: https://docs.anthropic.com/en/docs/about-claude/models
        return [
            "opus",
            "sonnet",
            "haiku",
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
            argv.extend(["--resume", resume_session])
        elif continue_last:
            argv.append("--continue")
        if yolo:
            argv.append("--dangerously-skip-permissions")
        if model:
            argv.extend(["--model", model])
        for d in extra_dirs or []:
            argv.extend(["--add-dir", d])
        return argv

    def append_ide_context(self, argv: list[str], editor_ctx: dict) -> None:
        if not editor_ctx:
            return
        prompt = _build_ide_context_prompt(editor_ctx)
        argv.extend(["--append-system-prompt", prompt])

    # --- session management ---

    def sessions_dir(self, cwd: str | None = None) -> pathlib.Path | None:
        cwd = cwd or os.getcwd()
        slug = cwd.replace("/", "-")
        d = pathlib.Path.home() / ".claude" / "projects" / slug
        return d if d.is_dir() else None

    def list_sessions(self, cwd: str | None = None) -> set[str]:
        d = self.sessions_dir(cwd)
        if not d:
            return set()
        return {f.stem for f in d.glob("*.jsonl")}

    def session_exists(self, session_id: str, cwd: str | None = None) -> bool:
        d = self.sessions_dir(cwd)
        if d and (d / f"{session_id}.jsonl").exists():
            return True
        # Fallback: search all project directories
        projects_dir = pathlib.Path.home() / ".claude" / "projects"
        if not projects_dir.is_dir():
            return False
        for project_dir in projects_dir.iterdir():
            if project_dir.is_dir() and (project_dir / f"{session_id}.jsonl").exists():
                return True
        return False

    # --- install instructions ---

    def install_lines(self) -> list[str]:
        RESET, DIM, CYAN, YELLOW = "\033[0m", "\033[2m", "\033[36m", "\033[33m"
        return [
            f"  {YELLOW}Claude Code{RESET}",
            f"  {DIM}https://code.claude.com/docs/en/quickstart{RESET}",
            f"  {CYAN}curl -fsSL https://claude.ai/install.sh | bash{RESET}",
        ]


def _build_ide_context_prompt(editor_ctx: dict) -> str:
    """Build the IDE context prompt string shared by context-injection methods."""
    from shared.ide_state_writer import get_state_file_path

    lines: list[str] = [
        "## Zen IDE Context",
        "You are running inside Zen IDE. The user has the following editor state:",
    ]
    if editor_ctx.get("active_file"):
        lines.append(f"- Active file (currently viewing): {editor_ctx['active_file']}")
    if editor_ctx.get("open_files"):
        lines.append(f"- Open files: {', '.join(editor_ctx['open_files'])}")
    if editor_ctx.get("workspace_folders"):
        lines.append(f"- Workspace folders: {', '.join(editor_ctx['workspace_folders'])}")
    if editor_ctx.get("workspace_file"):
        lines.append(f"- Workspace file: {editor_ctx['workspace_file']}")
    if editor_ctx.get("git_branches"):
        branches = editor_ctx["git_branches"]
        if len(branches) == 1:
            repo, branch = next(iter(branches.items()))
            lines.append(f"- Git branch: {repo} ({branch})")
        else:
            lines.append("- Git branches:")
            for repo, branch in branches.items():
                lines.append(f"  - {repo}: {branch}")
    elif editor_ctx.get("git_branch"):
        lines.append(f"- Git branch: {editor_ctx['git_branch']}")

    state_path = get_state_file_path()
    lines.append(
        f"\nThis state was captured at launch. For the latest editor state during this conversation, read: {state_path}"
    )
    return "\n".join(lines)
