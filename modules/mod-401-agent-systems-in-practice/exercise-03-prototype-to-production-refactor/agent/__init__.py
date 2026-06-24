"""AFTER: the layered, tested agent codebase."""

from __future__ import annotations

from .agent import run_agent
from .clients import (
    DemoModelAdapter,
    LocalToolTransport,
    ModelClient,
    ToolTransport,
)
from .config import AgentConfig
from .domain import ModelDecision, parse_decision, shape_observation

__all__ = [
    "AgentConfig",
    "DemoModelAdapter",
    "LocalToolTransport",
    "ModelClient",
    "ModelDecision",
    "ToolTransport",
    "parse_decision",
    "run_agent",
    "shape_observation",
]
