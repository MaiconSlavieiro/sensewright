"""Tests for the reasoning-effort config surface and God control."""

from __future__ import annotations

import pytest

from sims_sense_sidecar.config import AgentsConfig, LLMConfig, ProviderConfig, Settings
from sims_sense_sidecar.god.controls import (
    apply_values_to_agents_config,
    get_control,
    values_from_settings,
)
from sims_sense_sidecar.llm.base import normalize_reasoning_effort


def test_normalize_reasoning_effort():
    assert normalize_reasoning_effort("low") == "low"
    assert normalize_reasoning_effort("MIN") == "minimal"
    assert normalize_reasoning_effort("High") == "high"
    assert normalize_reasoning_effort("none") == "none"
    assert normalize_reasoning_effort("off") is None
    assert normalize_reasoning_effort("auto") is None
    assert normalize_reasoning_effort("") is None
    assert normalize_reasoning_effort(None) is None
    assert normalize_reasoning_effort("bogus") is None


def test_config_defaults_disable_reasoning():
    assert LLMConfig().reasoning_effort == "none"
    assert AgentsConfig().initiative.reasoning_effort is None
    assert ProviderConfig().supports_reasoning is False


def test_reasoning_control_present_and_validates():
    spec = get_control("reasoning_effort")
    assert spec is not None
    assert spec.kind == "select"
    assert spec.default == "none"
    assert spec.validate("minimal") == "minimal"
    with pytest.raises(ValueError):
        spec.validate("bogus")


def test_values_from_settings_reports_effort():
    settings = Settings()

    values = values_from_settings(settings)

    assert values["reasoning_effort"] == "none"


def test_apply_values_to_agents_config_maps_effort():
    patch = apply_values_to_agents_config({"reasoning_effort": "minimal"})

    assert patch["initiative"]["reasoning_effort"] == "minimal"
