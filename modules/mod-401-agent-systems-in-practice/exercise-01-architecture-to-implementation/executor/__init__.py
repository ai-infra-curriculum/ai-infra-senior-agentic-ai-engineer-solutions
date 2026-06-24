"""Tool-executor subsystem: the contract plus its implementations."""

from __future__ import annotations

from .caching import CachingExecutor
from .contract import (
    STATUS_ERROR,
    STATUS_OK,
    Store,
    ToolCall,
    ToolExecutor,
    ToolResult,
    Transport,
)
from .real import RealExecutor
from .store import InMemoryStore
from .stub import StubExecutor

__all__ = [
    "STATUS_ERROR",
    "STATUS_OK",
    "CachingExecutor",
    "InMemoryStore",
    "RealExecutor",
    "Store",
    "StubExecutor",
    "ToolCall",
    "ToolExecutor",
    "ToolResult",
    "Transport",
]
