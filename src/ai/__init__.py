"""
AI module for Zen IDE.

Contains the AI Terminal view and CLI provider implementations.
"""

__all__ = [
    "AITerminalView",
]

# Lazy imports
_LAZY_IMPORTS = {
    "AITerminalView": ".ai_terminal_view",
}


def __getattr__(name):
    if name in _LAZY_IMPORTS:
        import importlib

        module = importlib.import_module(_LAZY_IMPORTS[name], __name__)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
