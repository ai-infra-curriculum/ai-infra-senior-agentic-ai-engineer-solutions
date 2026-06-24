"""Typed config loaded from the environment. No secrets in source (Task 2).

Removing the hard-coded key is both the first refactor step and a security fix.
Required values fail fast at load time with a clear message rather than surfacing
as a confusing auth error deep in the loop.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_MODEL_NAME = "demo-model-v1"
DEFAULT_MAX_STEPS = 4


@dataclass(frozen=True)
class AgentConfig:
    api_key: str
    model_name: str
    max_steps: int

    @staticmethod
    def from_env(env: dict[str, str] | None = None) -> "AgentConfig":
        source = os.environ if env is None else env
        api_key = source.get("AGENT_API_KEY")
        if not api_key:
            raise ValueError(
                "AGENT_API_KEY is required; set it in the environment "
                "(never hard-code it in source)."
            )
        return AgentConfig(
            api_key=api_key,
            model_name=source.get("AGENT_MODEL_NAME", DEFAULT_MODEL_NAME),
            max_steps=int(source.get("AGENT_MAX_STEPS", str(DEFAULT_MAX_STEPS))),
        )
