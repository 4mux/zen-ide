"""
TreeItem — data class representing a file or directory in the tree.
"""

from pathlib import Path
from typing import List, Optional


class TreeItem:
    """Represents a file or directory in the tree."""

    def __init__(
        self,
        name: str,
        path: Path,
        is_dir: bool,
        depth: int = 0,
        parent: Optional["TreeItem"] = None,
        expanded: bool = False,
        is_last: bool = False,
        git_status: str = "",
    ):
        self.name = name
        self.path = path
        self.is_dir = is_dir
        self.depth = depth
        self.parent = parent
        self.expanded = expanded
        self.is_last = is_last
        self.git_status = git_status
        self.children: List["TreeItem"] = []

    @property
    def is_expandable(self) -> bool:
        """Alias for is_dir — used by ZenTree base class."""
        return self.is_dir
