from .base import BasePlayer

# debug.py is not included in published package
try:
    from .debug import DebugPlayer
except ImportError:
    DebugPlayer = None  # type: ignore

__all__ = ["BasePlayer", "DebugPlayer"]
