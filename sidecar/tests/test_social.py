"""Tests for the v0.3 R5 SocialLayer (sim<->sim dialogue channel)."""

from __future__ import annotations

from sensewright_sidecar.agent.social import (
    DEFAULT_MAX_PAIRS,
    DEFAULT_PAIR_COOLDOWN_SECONDS,
    DIALOGUE_MAX_LINES,
    Dialogue,
    SocialLayer,
    clean_line,
    render_dialogue,
    template_dialogue,
)
from sensewright_sidecar.config import AgentsConfig, LayersConfig, Settings


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


# ─── clean_line ──────────────────────────────────────────────────────────


def test_clean_line_strips_and_accepts_normal_text():
    assert clean_line("  Hello there!  ") == "Hello there!"
    assert clean_line('"Quoted line"') == "Quoted line"
    assert clean_line("'Single quoted'") == "Single quoted"


def test_clean_line_rejects_empty_and_punctuation_only():
    assert clean_line("") == ""
    assert clean_line("   ") == ""
    assert clean_line("...") == ""
    assert clean_line("!!!") == ""
    assert clean_line(".,;:") == ""


def test_clean_line_rejects_meta_commentary():
    assert clean_line("The user asked me to...") == ""
    assert clean_line("As an AI, I cannot...") == ""
    assert clean_line("I don't have access to...") == ""
    assert clean_line("Here is the response:") == ""
    assert clean_line("I'm sorry, but...") == ""


# ─── template_dialogue ───────────────────────────────────────────────────


def test_template_dialogue_shape_and_defaults():
    dlg = template_dialogue({}, {}, a_id=1, b_id=2)

    assert isinstance(dlg, Dialogue)
    assert dlg.a == 1
    assert dlg.b == 2
    assert dlg.source == "template"
    assert len(dlg.lines) == 2
    assert dlg.lines[0]["speaker"] == "a"
    assert dlg.lines[1]["speaker"] == "b"
    assert all("text" in line and line["text"] for line in dlg.lines)
    assert all("tone" in line for line in dlg.lines)


def test_template_dialogue_respects_relationship_type():
    dlg = template_dialogue({}, {}, relationship={"type": "romantic"}, a_id=1, b_id=2)
    assert "quiet moment" in dlg.topic.lower()

    dlg = template_dialogue({}, {}, relationship={"type": "family"}, a_id=1, b_id=2)
    assert "family" in dlg.topic.lower()

    dlg = template_dialogue({}, {}, relationship={"type": "friend"}, a_id=1, b_id=2)
    assert "catching up" in dlg.topic.lower()

    dlg = template_dialogue({}, {}, relationship={"level": -50}, a_id=1, b_id=2)
    assert "tense" in dlg.topic.lower()


# ─── Dialogue.to_dict / intents ──────────────────────────────────────────


def test_dialogue_to_dict_is_json_serializable():
    dlg = template_dialogue({"name": "Ana"}, {"name": "Bob"}, a_id=1, b_id=2)
    data = dlg.to_dict()
    assert data["a"] == 1
    assert data["b"] == 2
    assert data["source"] == "template"
    assert len(data["lines"]) == 2
    # Ensure it's actually JSON serializable
    import json
    json.dumps(data)


def test_dialogue_intents_returns_two_speak_intents():
    dlg = Dialogue(
        a=1,
        b=2,
        lines=[
            {"speaker": "a", "text": "Hi!", "tone": "friendly"},
            {"speaker": "b", "text": "Hello!", "tone": "warm"},
        ],
        topic="greeting",
        source="template",
    )
    intents = dlg.intents()
    assert len(intents) == 2
    # First intent: a -> b
    assert intents[0]["sim_id"] == 1
    assert intents[0]["target_sim_id"] == 2
    assert intents[0]["kind"] == "speak"
    assert intents[0]["params"]["text"] == "Hi!"
    assert intents[0]["params"]["tone"] == "friendly"
    assert intents[0]["reason"] == "greeting"
    assert intents[0]["expires_at"] == "next_sleep"
    assert intents[0]["priority"] == 0
    assert intents[0]["source"] == "agent"
    # Legacy fields for /v1/autonomy/directives alias
    assert intents[0]["name"] == "say_to"
    assert intents[0]["args"]["sim_id"] == 1
    assert intents[0]["args"]["target_sim_id"] == 2
    assert intents[0]["args"]["message"] == "Hi!"
    assert intents[0]["args"]["tone"] == "friendly"
    # Second intent: b -> a
    assert intents[1]["sim_id"] == 2
    assert intents[1]["target_sim_id"] == 1


def test_dialogue_intents_skips_empty_lines():
    dlg = Dialogue(
        a=1,
        b=2,
        lines=[
            {"speaker": "a", "text": "Hi!", "tone": "friendly"},
            {"speaker": "b", "text": "", "tone": "friendly"},  # empty
            {"speaker": "a", "text": "How are you?", "tone": "casual"},
        ],
        topic="chat",
        source="llm",
    )
    intents = dlg.intents()
    # Only non-empty lines produce intents
    assert len(intents) == 2
    assert intents[0]["params"]["text"] == "Hi!"
    assert intents[1]["params"]["text"] == "How are you?"


# ─── render_dialogue ─────────────────────────────────────────────────────


async def test_render_dialogue_without_registry_uses_template():
    dlg = await render_dialogue({}, {}, None, None, "en", 1, 2)
    assert dlg.source == "template"
    assert dlg.a == 1
    assert dlg.b == 2


async def test_render_dialogue_parses_valid_llm_json():
    registry = FakeRegistry(
        '{"topic": "coffee", "lines": [{"speaker": "a", "text": "Want coffee?", "tone": "casual"}, {"speaker": "b", "text": "Yes please!", "tone": "warm"}]}'
    )
    dlg = await render_dialogue({"name": "Ana"}, {"name": "Bob"}, None, registry, "pt-BR", 1, 2)
    assert dlg.source == "llm"
    assert dlg.topic == "coffee"
    assert len(dlg.lines) == 2
    assert dlg.lines[0]["text"] == "Want coffee?"
    assert dlg.lines[1]["text"] == "Yes please!"
    assert registry.calls == 1


async def test_render_dialogue_strips_markdown_fences():
    registry = FakeRegistry(
        '```json\n{"topic": "test", "lines": [{"speaker": "a", "text": "Hi", "tone": "friendly"}]}\n```'
    )
    dlg = await render_dialogue({}, {}, None, registry, "en", 1, 2)
    assert dlg.source == "llm"
    assert dlg.topic == "test"


async def test_render_dialogue_falls_back_on_bad_json():
    registry = FakeRegistry("not json at all")
    dlg = await render_dialogue({}, {}, None, registry, "en", 1, 2)
    assert dlg.source == "template"


async def test_render_dialogue_falls_back_on_empty_lines():
    registry = FakeRegistry('{"topic": "test", "lines": []}')
    dlg = await render_dialogue({}, {}, None, registry, "en", 1, 2)
    assert dlg.source == "template"


async def test_render_dialogue_falls_back_on_invalid_speaker():
    registry = FakeRegistry(
        '{"topic": "test", "lines": [{"speaker": "c", "text": "Hi", "tone": "friendly"}]}'
    )
    dlg = await render_dialogue({}, {}, None, registry, "en", 1, 2)
    assert dlg.source == "template"


async def test_render_dialogue_falls_back_on_clean_line_rejection():
    registry = FakeRegistry(
        '{"topic": "test", "lines": [{"speaker": "a", "text": "The user wants...", "tone": "friendly"}]}'
    )
    dlg = await render_dialogue({}, {}, None, registry, "en", 1, 2)
    assert dlg.source == "template"


async def test_render_dialogue_respects_max_lines():
    registry = FakeRegistry(
        '{"topic": "long", "lines": ['
        '{"speaker": "a", "text": "Line 1", "tone": "friendly"},'
        '{"speaker": "b", "text": "Line 2", "tone": "friendly"},'
        '{"speaker": "a", "text": "Line 3", "tone": "friendly"}'
        "]}"
    )
    dlg = await render_dialogue({}, {}, None, registry, "en", 1, 2)
    assert len(dlg.lines) == DIALOGUE_MAX_LINES


# ─── SocialLayer.configure ───────────────────────────────────────────────


def test_configure_defaults_when_missing():
    layer = SocialLayer()
    # Defaults from __init__
    assert layer.enabled is True
    assert layer.max_pairs == DEFAULT_MAX_PAIRS
    assert layer.pair_cooldown == DEFAULT_PAIR_COOLDOWN_SECONDS

    # Configure with minimal settings (no agents.layers.social, no agents.social)
    settings = Settings()
    layer.configure(settings)
    assert layer.enabled is True
    assert layer.max_pairs == DEFAULT_MAX_PAIRS
    assert layer.pair_cooldown == DEFAULT_PAIR_COOLDOWN_SECONDS


def test_configure_reads_layers_social_enabled():
    settings = Settings(agents=AgentsConfig(layers=LayersConfig(social=False)))
    layer = SocialLayer()
    layer.configure(settings)
    assert layer.enabled is False

    settings = Settings(agents=AgentsConfig(layers=LayersConfig(social=True)))
    layer = SocialLayer()
    layer.configure(settings)
    assert layer.enabled is True


def test_configure_reads_agents_social_max_pairs_and_cooldown():
    # Create a settings-like object with agents.social attribute
    class _SocialCfg:
        max_pairs_per_tick = 3
        pair_cooldown_seconds = 90.0

    class _AgentsCfg:
        layers = LayersConfig(social=True)
        social = _SocialCfg()

    class _Settings:
        agents = _AgentsCfg()

    layer = SocialLayer()
    layer.configure(_Settings())
    assert layer.max_pairs == 3
    assert layer.pair_cooldown == 90.0


def test_configure_bounds_check():
    class _SocialCfg:
        max_pairs_per_tick = 0  # should become 1
        pair_cooldown_seconds = -5.0  # should become 0.0

    class _AgentsCfg:
        layers = LayersConfig(social=True)
        social = _SocialCfg()

    class _Settings:
        agents = _AgentsCfg()

    layer = SocialLayer()
    layer.configure(_Settings())
    assert layer.max_pairs == 1
    assert layer.pair_cooldown == 0.0


# ─── SocialLayer.eligible ────────────────────────────────────────────────


def test_eligible_filters_sleeping_and_autonomy_off():
    sims = [
        {"sim_id": 1, "sleeping": False, "autonomy": "full"},
        {"sim_id": 2, "sleeping": True, "autonomy": "full"},
        {"sim_id": 3, "sleeping": False, "autonomy": "off"},
        {"sim_id": 4, "sleeping": False, "autonomy": "semi"},
    ]
    layer = SocialLayer()
    eligible = layer.eligible(sims)
    assert [s["sim_id"] for s in eligible] == [1, 4]


def test_eligible_deduplicates_by_sim_id():
    sims = [
        {"sim_id": 1, "sleeping": False, "autonomy": "full"},
        {"sim_id": 1, "sleeping": False, "autonomy": "full"},  # duplicate
        {"sim_id": 2, "sleeping": False, "autonomy": "full"},
    ]
    layer = SocialLayer()
    eligible = layer.eligible(sims)
    assert [s["sim_id"] for s in eligible] == [1, 2]


def test_eligible_requires_seated_membership_when_provided():
    sims = [
        {"sim_id": 1, "sleeping": False, "autonomy": "full"},
        {"sim_id": 2, "sleeping": False, "autonomy": "full"},
        {"sim_id": 3, "sleeping": False, "autonomy": "full"},
    ]
    layer = SocialLayer()
    eligible = layer.eligible(sims, seated_ids=[1, 3])
    assert [s["sim_id"] for s in eligible] == [1, 3]


def test_eligible_handles_invalid_sim_id():
    sims = [
        {"sim_id": "not-an-int", "sleeping": False, "autonomy": "full"},
        {"sim_id": 2, "sleeping": False, "autonomy": "full"},
        {"sim_id": None, "sleeping": False, "autonomy": "full"},
    ]
    layer = SocialLayer()
    eligible = layer.eligible(sims)
    assert [s["sim_id"] for s in eligible] == [2]


# ─── SocialLayer.pick_pairs ──────────────────────────────────────────────


def test_pick_pairs_excludes_player_sims():
    sims = [
        {"sim_id": 1, "sleeping": False, "autonomy": "full", "is_player": True},
        {"sim_id": 2, "sleeping": False, "autonomy": "full", "is_player": False},
        {"sim_id": 3, "sleeping": False, "autonomy": "full", "is_player": False},
    ]
    layer = SocialLayer(max_pairs=1)
    pairs = layer.pick_pairs(sims)
    # Only non-player Sims (2, 3) should pair
    assert len(pairs) == 1
    a, b = pairs[0]
    assert a["sim_id"] in (2, 3)
    assert b["sim_id"] in (2, 3)
    assert a["sim_id"] != b["sim_id"]


def test_pick_pairs_returns_empty_when_fewer_than_two_non_player():
    sims = [
        {"sim_id": 1, "sleeping": False, "autonomy": "full", "is_player": True},
        {"sim_id": 2, "sleeping": False, "autonomy": "full", "is_player": True},
    ]
    layer = SocialLayer()
    pairs = layer.pick_pairs(sims)
    assert pairs == []


def test_pick_pairs_enforces_cooldown():
    sims = [
        {"sim_id": 1, "sleeping": False, "autonomy": "full", "is_player": False},
        {"sim_id": 2, "sleeping": False, "autonomy": "full", "is_player": False},
    ]
    layer = SocialLayer(max_pairs=1, pair_cooldown_seconds=100.0)
    # First call should succeed
    pairs1 = layer.pick_pairs(sims, now=1000.0)
    assert len(pairs1) == 1
    # Second call within cooldown should return empty
    pairs2 = layer.pick_pairs(sims, now=1050.0)
    assert pairs2 == []
    # Third call after cooldown should succeed
    pairs3 = layer.pick_pairs(sims, now=1150.0)
    assert len(pairs3) == 1


def test_pick_pairs_returns_disjoint_pairs():
    sims = [
        {"sim_id": i, "sleeping": False, "autonomy": "full", "is_player": False}
        for i in range(1, 7)
    ]
    layer = SocialLayer(max_pairs=3)
    pairs = layer.pick_pairs(sims, now=1000.0)
    assert len(pairs) == 3
    used = set()
    for a, b in pairs:
        assert a["sim_id"] not in used
        assert b["sim_id"] not in used
        used.add(a["sim_id"])
        used.add(b["sim_id"])


def test_pick_pairs_respects_max_pairs():
    sims = [
        {"sim_id": i, "sleeping": False, "autonomy": "full", "is_player": False}
        for i in range(1, 11)
    ]
    layer = SocialLayer(max_pairs=2)
    pairs = layer.pick_pairs(sims, now=1000.0)
    assert len(pairs) == 2


def test_pick_pairs_deterministic_with_rng():
    import random

    sims = [
        {"sim_id": i, "sleeping": False, "autonomy": "full", "is_player": False}
        for i in range(1, 7)
    ]
    rng1 = random.Random(42)
    rng2 = random.Random(42)
    layer1 = SocialLayer(max_pairs=3, rng=rng1)
    layer2 = SocialLayer(max_pairs=3, rng=rng2)
    pairs1 = layer1.pick_pairs(sims, now=1000.0)
    pairs2 = layer2.pick_pairs(sims, now=1000.0)
    assert [(a["sim_id"], b["sim_id"]) for a, b in pairs1] == [
        (a["sim_id"], b["sim_id"]) for a, b in pairs2
    ]


# ─── SocialLayer.maybe_dialogue ──────────────────────────────────────────


async def test_maybe_dialogue_returns_dialogue_with_valid_pair():
    sims = [
        {"sim_id": 1, "sleeping": False, "autonomy": "full", "is_player": False, "relationships": []},
        {"sim_id": 2, "sleeping": False, "autonomy": "full", "is_player": False, "relationships": []},
    ]
    layer = SocialLayer(max_pairs=1)
    dlg = await layer.maybe_dialogue(player_id="local", save_id="s1", sims=sims, lang="en")
    assert dlg is not None
    assert isinstance(dlg, Dialogue)
    assert dlg.a in (1, 2)
    assert dlg.b in (1, 2)
    assert dlg.a != dlg.b


async def test_maybe_dialogue_returns_none_when_no_pairs():
    sims = [
        {"sim_id": 1, "sleeping": False, "autonomy": "full", "is_player": True},
    ]
    layer = SocialLayer()
    dlg = await layer.maybe_dialogue(player_id="local", save_id="s1", sims=sims, lang="en")
    assert dlg is None


async def test_maybe_dialogue_uses_fake_registry_and_returns_llm_dialogue():
    sims = [
        {"sim_id": 1, "sleeping": False, "autonomy": "full", "is_player": False, "relationships": []},
        {"sim_id": 2, "sleeping": False, "autonomy": "full", "is_player": False, "relationships": []},
    ]
    registry = FakeRegistry(
        '{"topic": "books", "lines": [{"speaker": "a", "text": "Read any good books?", "tone": "curious"}, {"speaker": "b", "text": "Just finished one!", "tone": "excited"}]}'
    )
    layer = SocialLayer(max_pairs=1, registry=registry)
    dlg = await layer.maybe_dialogue(player_id="local", save_id="s1", sims=sims, lang="en")
    assert dlg is not None
    assert dlg.source == "llm"
    assert dlg.topic == "books"
    assert registry.calls == 1


async def test_maybe_dialogue_falls_back_to_template_on_broken_registry():
    sims = [
        {"sim_id": 1, "sleeping": False, "autonomy": "full", "is_player": False, "relationships": []},
        {"sim_id": 2, "sleeping": False, "autonomy": "full", "is_player": False, "relationships": []},
    ]
    registry = FakeRegistry("not json")
    layer = SocialLayer(max_pairs=1, registry=registry)
    dlg = await layer.maybe_dialogue(player_id="local", save_id="s1", sims=sims, lang="en")
    assert dlg is not None
    assert dlg.source == "template"


async def test_maybe_dialogue_records_pair_time():
    sims = [
        {"sim_id": 1, "sleeping": False, "autonomy": "full", "is_player": False, "relationships": []},
        {"sim_id": 2, "sleeping": False, "autonomy": "full", "is_player": False, "relationships": []},
    ]
    layer = SocialLayer(max_pairs=1, pair_cooldown_seconds=100.0)
    await layer.maybe_dialogue(player_id="local", save_id="s1", sims=sims, lang="en")
    # Second call should be blocked by cooldown (pick_pairs uses clock)
    # We can't easily test cooldown without mocking clock, but we can verify the pair was recorded
    assert len(layer._last_pair_at) == 1


# ─── SocialLayer.plan ────────────────────────────────────────────────────


async def test_plan_returns_dialogues_for_each_pair_up_to_max_pairs():
    sims = [
        {"sim_id": i, "sleeping": False, "autonomy": "full", "is_player": False, "relationships": []}
        for i in range(1, 7)
    ]
    layer = SocialLayer(max_pairs=2)
    dialogues = await layer.plan(player_id="local", save_id="s1", sims=sims, lang="en")
    assert len(dialogues) == 2
    for dlg in dialogues:
        assert isinstance(dlg, Dialogue)


async def test_plan_never_raises_even_on_errors():
    # Simulate an error in maybe_dialogue by passing a registry that raises
    class BrokenRegistry:
        async def complete(self, messages, **kwargs):
            raise RuntimeError("boom")

    sims = [
        {"sim_id": 1, "sleeping": False, "autonomy": "full", "is_player": False, "relationships": []},
        {"sim_id": 2, "sleeping": False, "autonomy": "full", "is_player": False, "relationships": []},
    ]
    layer = SocialLayer(max_pairs=1, registry=BrokenRegistry())
    # Should not raise, returns empty list (fallback to template works, but if template also fails...)
    dialogues = await layer.plan(player_id="local", save_id="s1", sims=sims, lang="en")
    # Template fallback works, so we get a dialogue
    assert len(dialogues) == 1
    assert dialogues[0].source == "template"


# ─── SocialLayer.snapshot ────────────────────────────────────────────────


def test_snapshot_returns_expected_keys():
    layer = SocialLayer(max_pairs=2, pair_cooldown_seconds=90.0)
    snap = layer.snapshot()
    assert snap["enabled"] is True
    assert snap["max_pairs"] == 2
    assert snap["pair_cooldown_s"] == 90.0
    assert snap["pairs_seen"] == 0

    # After a pair is recorded
    layer._last_pair_at[frozenset({1, 2})] = 1000.0
    snap = layer.snapshot()
    assert snap["pairs_seen"] == 1

def test_template_dialogue_localizes_pt_br():
    dlg = template_dialogue({}, {}, a_id=1, b_id=2, lang="pt-BR")
    assert "Oi" in dlg.lines[0]["text"]
    assert "Oi" in dlg.lines[1]["text"]

