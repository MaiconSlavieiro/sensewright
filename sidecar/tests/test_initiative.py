"""Tests for the LLM impulse builder and its deterministic fallback (A3)."""

from __future__ import annotations

from typing import Any

from sensewright_sidecar.agent.agency import ImpulseJob
from sensewright_sidecar.agent.initiative import (
    _clean_thought,
    build_impulse,
    build_impulse_prompt,
    impulse_tools,
    rule_based_impulse,
)


def job(kind: str = "idle", event: dict[str, Any] | None = None, sim_id: int = 10) -> ImpulseJob:
    return ImpulseJob(
        priority=2,
        seq=1,
        kind=kind,
        player_id="local",
        save_id="save1",
        sim_id=sim_id,
        lang="en",
        event=event,
    )


class FakeCall:
    def __init__(self, call_id: str, name: str, arguments: dict[str, Any]) -> None:
        self.id = call_id
        self.name = name
        self.arguments = arguments


class FakeResponse:
    def __init__(
        self,
        text: str = "",
        tool_calls: tuple[FakeCall, ...] = (),
        provider: str | None = "fake",
    ) -> None:
        self.text = text
        self.tool_calls = tool_calls
        self.provider = provider


class FakeRegistry:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls: list[tuple[list[dict[str, Any]], dict[str, Any]]] = []

    async def complete(self, messages: list[dict[str, Any]], **kwargs: Any) -> FakeResponse:
        self.calls.append((messages, kwargs))
        return self.response


class BoomRegistry:
    async def complete(self, messages: list[dict[str, Any]], **kwargs: Any) -> Any:
        raise RuntimeError("no network")


def test_impulse_tools_filtered_by_autonomy():
    assert impulse_tools("off") == []
    assert impulse_tools("suggest") == ["spontaneous_line"]
    assert "say_to" not in impulse_tools("suggest")
    assert "say_to" in impulse_tools("semi")
    assert "act_out" in impulse_tools("full")
    assert "add_trait" in impulse_tools("full")


def test_rule_based_idle_returns_thought_only():
    result = rule_based_impulse(job=job("idle"), profile={"name": "Ana"}, world={}, lang="en")

    assert result["used_llm"] is False
    assert result["directives"] == []
    assert result["thought"]


def test_rule_based_reaction_emits_directive():
    result = rule_based_impulse(
        job=job("reaction", event={"type": "fire", "importance": 2.0}),
        profile={"name": "Ana"},
        world={},
        lang="en",
    )

    assert len(result["directives"]) == 1
    directive = result["directives"][0]
    assert directive["sim_id"] == 10
    assert directive["source"] == "agent"
    assert directive["name"] in {"set_mood", "spontaneous_line", "say_to"}
    assert {"id", "sim_id", "name", "args", "thought", "narration", "priority", "source"} <= set(
        directive
    )


def test_rule_based_sleep_is_empty():
    result = rule_based_impulse(job=job("sleep"), profile={}, world={}, lang="en")

    assert result == {
        "directives": [],
        "intents": [],
        "thought": "",
        "provider": None,
        "used_llm": False,
    }


def test_build_impulse_prompt_includes_lang_and_situation():
    messages = build_impulse_prompt(
        job=job("idle"),
        profile={"name": "Ana"},
        world={"zone": {"time_of_day": "night"}, "sims": {"11": {"sim_id": 11, "mood": "happy"}}},
        memories=[{"text": "saw a fire"}],
        lang="pt-BR",
    )

    assert messages[0]["role"] == "system"
    assert "pt-BR" in messages[0]["content"]
    assert "night" in messages[1]["content"]
    assert "saw a fire" in messages[1]["content"]


async def test_build_impulse_falls_back_without_registry():
    result = await build_impulse(
        job=job("idle"),
        profile={},
        world={},
        memories=[],
        registry=None,
        lang="en",
        autonomy="semi",
    )

    assert result["used_llm"] is False
    assert result["directives"] == []


def test_clean_thought_strips_leading_prefix_keeping_line():
    assert _clean_thought("Here's a thought:\n\nI wonder about Beto.") == "I wonder about Beto."
    assert _clean_thought("Thought: I should check on Beto.") == "I should check on Beto."


def test_clean_thought_drops_reasoning_trace():
    trace = "Here's a thinking process:\n\n1. Analyze User Input:\n - time: afternoon"
    assert _clean_thought(trace) == ""


def test_clean_thought_drops_pt_br_meta():
    assert _clean_thought("O usuário me deu uma situação com Sims próximos.") == ""


def test_clean_thought_keeps_valid_line():
    line = "I wonder if Beto is still happy today."
    assert _clean_thought(line) == line


async def test_build_impulse_discards_meta_thought():
    # A reasoning model narrating the task instead of role-playing.
    response = FakeResponse(text="The user gives a situation with time and nearby Sims.")
    registry = FakeRegistry(response)

    result = await build_impulse(
        job=job("idle"),
        profile={"name": "Ana"},
        world={},
        memories=[],
        registry=registry,
        lang="en",
        autonomy="semi",
    )

    assert result["used_llm"] is False
    assert "the user" not in result["thought"].lower()
    assert result["thought"]


async def test_build_impulse_discards_punctuation_thought():
    for text in (")", ".", "...", ""):
        result = await build_impulse(
            job=job("idle"),
            profile={"name": "Ana"},
            world={},
            memories=[],
            registry=FakeRegistry(FakeResponse(text=text)),
            lang="en",
            autonomy="semi",
        )
        assert result["used_llm"] is False
        assert result["thought"]


def test_build_impulse_prompt_forbids_meta_narration():
    messages = build_impulse_prompt(
        job=job("idle"),
        profile={"name": "Ana"},
        world={},
        memories=[],
        lang="en",
    )

    assert "first person" in messages[0]["content"]
    assert "call exactly one tool" in messages[0]["content"]
    assert "thinking process" in messages[0]["content"].lower()
    assert "first-person" in messages[1]["content"]
    assert "no preamble" in messages[1]["content"].lower()
    # The kind task must be formatted: no raw ``{name}`` placeholder leaks.
    assert "{name}" not in messages[1]["content"]


async def test_build_impulse_falls_back_when_registry_raises():
    result = await build_impulse(
        job=job("reaction", event={"type": "fire"}),
        profile={},
        world={},
        memories=[],
        registry=BoomRegistry(),
        lang="en",
        autonomy="semi",
    )

    assert result["used_llm"] is False
    assert len(result["directives"]) == 1


async def test_build_impulse_parses_tool_calls():
    response = FakeResponse(
        text="I feel chatty.",
        tool_calls=(FakeCall("c1", "spontaneous_line", {"text": "hello", "audience": "self"}),),
        provider="fake",
    )
    registry = FakeRegistry(response)

    result = await build_impulse(
        job=job("idle"),
        profile={"name": "Ana"},
        world={},
        memories=[{"text": "saw a fire"}],
        registry=registry,
        lang="en",
        autonomy="semi",
    )

    assert result["used_llm"] is True
    assert result["provider"] == "fake"
    assert result["thought"] == "I feel chatty."
    assert len(result["directives"]) == 1
    directive = result["directives"][0]
    assert directive["name"] == "spontaneous_line"
    assert directive["args"]["text"] == "hello"
    assert directive["id"] == "c1"
    assert directive["source"] == "agent"
    assert registry.calls[0][1]["max_tokens"] > 0


async def test_build_impulse_drops_disallowed_tools():
    response = FakeResponse(
        tool_calls=(FakeCall("c1", "say_to", {"message": "hi", "target_sim_id": 11}),),
    )

    result = await build_impulse(
        job=job("idle"),
        profile={},
        world={},
        memories=[],
        registry=FakeRegistry(response),
        lang="en",
        autonomy="suggest",
    )

    assert result["directives"] == []


async def test_build_impulse_limits_idle_to_one_action():
    response = FakeResponse(
        tool_calls=(
            FakeCall("c1", "spontaneous_line", {"text": "a"}),
            FakeCall("c2", "spontaneous_line", {"text": "b"}),
        ),
    )

    result = await build_impulse(
        job=job("idle"),
        profile={},
        world={},
        memories=[],
        registry=FakeRegistry(response),
        lang="en",
        autonomy="semi",
    )

    assert len(result["directives"]) == 1


async def test_build_impulse_sleep_skips_llm():
    registry = FakeRegistry(FakeResponse(text="should not be used"))

    result = await build_impulse(
        job=job("sleep"),
        profile={},
        world={},
        memories=[],
        registry=registry,
        lang="en",
        autonomy="full",
    )

    assert result["directives"] == []
    assert result["used_llm"] is False
    assert registry.calls == []


class SequenceRegistry:
    """Returns a queued response per call and records the call kwargs."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def complete(self, messages, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


async def test_build_impulse_retries_once_on_unusable_output():
    first = FakeResponse(text="Here's a thinking process:\n\n1. Analyze User Input:")
    second = FakeResponse(text="I wonder about Beto.", provider="fake")
    registry = SequenceRegistry([first, second])

    result = await build_impulse(
        job=job("idle"), profile={"name": "Ana"}, world={}, memories=[],
        registry=registry, lang="en", autonomy="semi",
    )

    assert result["used_llm"] is True
    assert result["thought"] == "I wonder about Beto."
    assert len(registry.calls) == 2


async def test_build_impulse_falls_back_after_all_unusable():
    registry = SequenceRegistry(
        [FakeResponse(text="thinking process"), FakeResponse(text="thinking process")]
    )

    result = await build_impulse(
        job=job("idle"), profile={"name": "Ana"}, world={}, memories=[],
        registry=registry, lang="en", autonomy="semi",
    )

    assert result["used_llm"] is False
    assert len(registry.calls) == 2


async def test_build_impulse_forwards_reasoning_effort():
    registry = SequenceRegistry([FakeResponse(text="hi")])

    await build_impulse(
        job=job("idle"), profile={"name": "Ana"}, world={}, memories=[],
        registry=registry, lang="en", autonomy="semi", reasoning_effort="minimal",
    )

    assert registry.calls[0]["reasoning_effort"] == "minimal"


async def test_build_impulse_parses_text_tool_call():
    # A free model that cannot emit native tool calls prints the call as JSON.
    response = FakeResponse(
        text='[[{"name": "say_to", "parameters": {"message": "oi", "target_sim_id": 11}}]]',
    )

    result = await build_impulse(
        job=job("idle"),
        profile={"name": "Ana"},
        world={},
        memories=[],
        registry=FakeRegistry(response),
        lang="pt-BR",
        autonomy="semi",
    )

    assert result["used_llm"] is True
    assert result["thought"] == ""
    assert len(result["directives"]) == 1
    assert result["directives"][0]["name"] == "say_to"
    assert result["directives"][0]["args"]["target_sim_id"] == 11


async def test_build_impulse_ignores_text_tool_call_for_disallowed_tool():
    response = FakeResponse(text='[{"name": "add_trait", "parameters": {"trait": "X"}}]')

    result = await build_impulse(
        job=job("idle"),
        profile={"name": "Ana"},
        world={},
        memories=[],
        registry=FakeRegistry(response),
        lang="en",
        autonomy="suggest",
    )

    assert result["directives"] == []


def test_build_impulse_prompt_lists_nearby_sim_ids():
    messages = build_impulse_prompt(
        job=job("idle", sim_id=10),
        profile={"name": "Ana"},
        world={
            "zone": {"time_of_day": "morning"},
            "sims": {
                "10": {"sim_id": 10, "full_name": "Ana", "mood": "happy"},
                "11": {"sim_id": 11, "full_name": "Beto", "mood": "fine"},
            },
        },
        memories=[],
        lang="en",
    )

    user = messages[1]["content"]
    assert "Beto (id=11" in user
    assert "exact id values" in user
    # The acting Sim must not be listed as a nearby target of itself.
    assert "Ana (id=10" not in user
