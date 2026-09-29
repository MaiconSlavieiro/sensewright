"""Tests for the R4 cognition layer (daily plan + goals at sleep)."""

from __future__ import annotations

from sims_sense_sidecar.agent.cognition import (
    CognitionLayer,
    make_daily_plan,
    render_plan,
    template_plan,
)
from sims_sense_sidecar.config import AgentsConfig, LayersConfig, Settings


class FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeRegistry:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls = 0

    async def complete(self, messages, **kwargs):
        self.calls += 1
        return FakeResponse(self.text)


def test_template_plan_has_focus_and_goals():
    plan = template_plan({}, [])

    assert plan["source"] == "template"
    assert plan["day_focus"]
    assert 1 <= len(plan["goals"]) <= 3


def test_template_plan_respects_existing_profile():
    plan = template_plan({"day_focus": "Finish the novel", "goals": ["Write", "Rest"]})

    assert plan["day_focus"] == "Finish the novel"
    assert plan["goals"] == ["Write", "Rest"]


async def test_make_daily_plan_without_registry_uses_template():
    plan = await make_daily_plan({}, [], None, "en")

    assert plan["source"] == "template"


async def test_make_daily_plan_parses_llm_json():
    registry = FakeRegistry('{"day_focus": "Make a friend", "goals": ["Chat", "Party"]}')

    plan = await make_daily_plan({"name": "Ana"}, [], registry, "pt-BR")

    assert plan["source"] == "llm"
    assert plan["day_focus"] == "Make a friend"
    assert plan["goals"] == ["Chat", "Party"]
    assert registry.calls == 1


async def test_make_daily_plan_falls_back_on_bad_json():
    registry = FakeRegistry("not json at all")

    plan = await make_daily_plan({}, [], registry, "en")

    assert plan["source"] == "template"


def test_render_plan_reads_stored_plan():
    profile = {"daily_plan": {"day_focus": "Work out", "goals": ["Gym", "Eat well"]}}

    text = render_plan(profile)

    assert "Work out" in text
    assert "Gym" in text


def test_render_plan_empty_without_plan():
    assert render_plan({}) == ""
    assert render_plan(None) == ""


def test_impulse_prompt_includes_daily_plan():
    from sims_sense_sidecar.agent.initiative import _describe_profile

    text = _describe_profile(
        {"daily_plan": {"day_focus": "Write the book", "goals": ["Write"]}}
    )

    assert "Write the book" in text


async def test_cognition_layer_disabled_returns_none():
    settings = Settings(agents=AgentsConfig(layers=LayersConfig(cognition=False)))
    layer = CognitionLayer(settings)

    assert layer.enabled is False
    assert await layer.think({}, [], None, "en") is None


async def test_cognition_layer_enabled_uses_registry():
    settings = Settings(agents=AgentsConfig(layers=LayersConfig(cognition=True)))
    layer = CognitionLayer(settings)
    registry = FakeRegistry('{"day_focus": "Explore", "goals": ["Walk"]}')

    plan = await layer.think({"name": "Ana"}, [], registry, "en")

    assert layer.enabled is True
    assert plan["source"] == "llm"
