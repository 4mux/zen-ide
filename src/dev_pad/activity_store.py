"""
Activity store helpers for Dev Pad.

Contains logging functions and utility helpers used by DevPad and other
parts of the application to record activities.
"""

import os
from datetime import datetime
from typing import Optional

from dev_pad.dev_pad_storage import get_dev_pad_storage
from icons import IconsManager


def _abbreviate_path(path: str, max_len: int = 50) -> str:
    """Abbreviate a file path to fit in a given length."""
    if not path:
        return ""
    if len(path) <= max_len:
        return path
    # Replace home dir with ~
    home = os.path.expanduser("~")
    if path.startswith(home):
        path = "~" + path[len(home) :]
    if len(path) <= max_len:
        return path
    # Truncate from the middle
    half = (max_len - 3) // 2
    return path[:half] + "..." + path[-half:]


def _get_activity_icon(activity_type: str) -> str:
    """Get an icon for the activity type."""
    icons = {
        "file_edit": IconsManager.EDIT,
        "file_open": IconsManager.FILE,
        "file_save": IconsManager.SAVE,
        "file_new": IconsManager.CLIPBOARD,
        "ai_chat": IconsManager.ROBOT,
        "ai_question": IconsManager.QUESTION,
        "git_checkout": IconsManager.GIT_BRANCH,
        "git_commit": IconsManager.CHECK,
        "git_push": IconsManager.ARROW_UP,
        "git_pull": IconsManager.ARROW_DOWN,
        "search": IconsManager.SEARCH,
        "terminal": IconsManager.TERMINAL,
        "error": IconsManager.ERROR,
        "debug": IconsManager.BUG,
        "test": IconsManager.FLASK,
        "build": IconsManager.HAMMER,
        "pr_review": IconsManager.EYE,
        "github_pr": IconsManager.GIT_MERGE,
        "note": IconsManager.PIN,
        "sketch": IconsManager.PENCIL,
    }
    return icons.get(activity_type, IconsManager.MODIFIED_DOT)


def _get_sketch_preview(content: str, max_lines: int = 8, max_width: int = 60) -> str:
    """Get a compact preview of sketch ASCII art content."""
    lines = content.split("\n")
    # Filter out empty lines and trim
    non_empty = [line for line in lines if line.strip()]
    if not non_empty:
        return ""
    preview_lines = non_empty[:max_lines]
    result = []
    for line in preview_lines:
        if len(line) > max_width:
            result.append(line[:max_width] + "…")
        else:
            result.append(line)
    if len(non_empty) > max_lines:
        result.append("  ...")
    return "\n".join(result)


# Helper functions for logging activities from other parts of the app


def log_file_activity(file_path: str, action: str = "open"):
    """Log a file-related activity."""
    storage = get_dev_pad_storage()
    filename = os.path.basename(file_path) if file_path else "Unknown"
    activity_type = f"file_{action}"
    title = f"{filename}"
    description = f"{action.capitalize()} {_abbreviate_path(file_path)}"

    storage.update_or_add_activity(
        activity_type=activity_type,
        title=title,
        description=description,
        link_type="file",
        link_target=file_path,
    )


def log_new_file_activity(tab_id: int) -> str:
    """Log a new/limbo file activity. Returns the activity ID."""
    storage = get_dev_pad_storage()
    activity = storage.add_activity(
        activity_type="file_new",
        title="Untitled (unsaved)",
        description="New file - not yet saved to disk",
        link_type="tab",
        link_target=str(tab_id),
    )
    return activity.id


def remove_new_file_activity(activity_id: str):
    """Remove a new/limbo file activity."""
    storage = get_dev_pad_storage()
    storage.delete_activity(activity_id)


def log_ai_activity(question: str, chat_id: Optional[str] = None, title: Optional[str] = None):
    """Log an AI chat activity.

    If *chat_id* (session ID) is provided, updates the existing row for that
    session (moving it to the top) instead of creating a duplicate.
    """
    storage = get_dev_pad_storage()
    display_title = title or "AI Chat"
    short_question = question[:80] + "..." if len(question) > 80 else question

    storage.update_or_add_activity(
        activity_type="ai_chat",
        title=display_title,
        description=short_question,
        link_type="ai_chat" if chat_id else None,
        link_target=chat_id,
    )


def log_git_activity(action: str, branch: str = "", repo_path: str = ""):
    """Log a git-related activity."""
    storage = get_dev_pad_storage()
    title = f"{action}"
    if branch:
        title += f" ({branch})"

    storage.add_activity(
        activity_type=f"git_{action.lower().replace(' ', '_')}",
        title=title,
        description=f"{action} on branch {branch}" if branch else action,
        link_type="repo" if repo_path else None,
        link_target=repo_path,
    )


def log_search_activity(query: str, results_count: int = 0):
    """Log a search activity."""
    storage = get_dev_pad_storage()
    storage.add_activity(
        activity_type="search",
        title=f'Search: "{query}"',
        description=f"Found {results_count} results" if results_count else f'Searched for "{query}"',
    )


def log_custom_activity(
    activity_type: str,
    title: str,
    description: str = "",
    link_type: Optional[str] = None,
    link_target: Optional[str] = None,
):
    """Log a custom activity."""
    storage = get_dev_pad_storage()
    storage.add_activity(
        activity_type=activity_type,
        title=title,
        description=description or title,
        link_type=link_type,
        link_target=link_target,
    )


def log_debug_activity(title: str, description: str = "", file_path: str = ""):
    """Log a debug session activity."""
    storage = get_dev_pad_storage()
    storage.update_or_add_activity(
        activity_type="debug",
        title=title,
        description=description or title,
        link_type="file" if file_path else None,
        link_target=file_path or None,
    )


def log_github_pr_activity(
    author: str,
    title: str,
    pr_url: str,
    repo_name: str = "",
    created_at: str = "",
):
    """Log a GitHub PR activity."""
    storage = get_dev_pad_storage()

    date_str = ""
    if created_at:
        try:
            dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            date_str = dt.strftime("%b %d, %Y")
        except (ValueError, AttributeError):
            pass

    display_title = f"{author}: {title}"
    date_part = f" ({date_str})" if date_str else ""
    description = f"PR in {repo_name}{date_part}" if repo_name else f"PR by {author}{date_part}"

    storage.update_or_add_activity(
        activity_type="github_pr",
        title=display_title,
        description=description,
        link_type="url",
        link_target=pr_url,
    )


def log_sketch_activity(content: str = "", file_path: str = ""):
    """Log a sketch pad activity. If file_path is given, link to the .zen_sketch file."""
    storage = get_dev_pad_storage()
    from sketch_pad.sketch_model import Board

    # Generate preview from content
    title = "Sketch Pad"
    description = "ASCII diagram"
    if content:
        try:
            board = Board.from_json(content)
            shape_count = len(board.shapes)
            description = f"ASCII diagram ({shape_count} shape{'s' if shape_count != 1 else ''})"
        except Exception:
            pass

    if file_path:
        title = os.path.basename(file_path)
        storage.update_or_add_activity(
            activity_type="sketch",
            title=title,
            description=description,
            link_type="file",
            link_target=file_path,
            metadata={"content": content} if content else {},
        )
    else:
        storage.update_or_add_activity(
            activity_type="sketch",
            title=title,
            description=description,
            link_type="sketch",
            link_target="sketch_pad",
            metadata={"content": content} if content else {},
        )
