"""Config loads from env and fails fast when the key is missing (Task 2)."""

from __future__ import annotations

import pytest

from agent import AgentConfig
from agent.config import DEFAULT_MAX_STEPS, DEFAULT_MODEL_NAME


def test_loads_from_env_with_defaults() -> None:
    config = AgentConfig.from_env({"AGENT_API_KEY": "k"})
    assert config.api_key == "k"
    assert config.model_name == DEFAULT_MODEL_NAME
    assert config.max_steps == DEFAULT_MAX_STEPS


def test_overrides_are_respected() -> None:
    config = AgentConfig.from_env(
        {"AGENT_API_KEY": "k", "AGENT_MODEL_NAME": "m2", "AGENT_MAX_STEPS": "7"}
    )
    assert config.model_name == "m2"
    assert config.max_steps == 7


def test_missing_key_fails_fast() -> None:
    with pytest.raises(ValueError, match="AGENT_API_KEY is required"):
        AgentConfig.from_env({})
