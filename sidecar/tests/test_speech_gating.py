"""Sidecar speech-gating tests (v0.4 P1): intent repair + surfaced annotation."""

from __future__ import annotations

from types import SimpleNamespace

from sensewright_sidecar.agent import graph
from sensewright_sidecar.agent.agency import ImpulseJob
from sensewright_sidecar.agent.speech import SpeechPolicy


def make_job(sim_id: int = 10) -> ImpulseJob:
    return ImpulseJob(
        priority=2,
        seq=1,
        kind="idle",
        player_id="local",
        save_id="save1",
        sim_id=sim_id,
        lang="en",
    )


def test_note_lang_adopts_the_client_language(monkeypatch):
    """The sidecar must follow the game language the mod reports."""
    monkeypatch.setattr(graph, "_current_lang", "en")
    graph._note_lang("pt-BR")
    assert graph._current_lang == "pt-BR"
    # Empty/None never clobbers the adopted language.
    graph._note_lang(None)
    graph._note_lang("")
    assert graph._current_lang == "pt-BR"


def test_repair_socialize_without_target_uses_partner():
    job = make_job()
    world = {"sims": {"11": {"sim_id": 11, "interaction_target_sim_id": 10}}}
    intent = {"name": "socialize", "kind": "speak", "args": {"reason": "hi"}, "params": {}}

    repaired = graph._repair_intent(intent, job, world)

    assert repaired is not None
    assert repaired["args"]["target_sim_id"] == 11
    assert repaired["name"] == "socialize"


def test_repair_socialize_without_target_degrades_to_murmur():
    job = make_job()
    intent = {"name": "socialize", "kind": "speak", "args": {"reason": "hello"}, "params": {}}

    repaired = graph._repair_intent(intent, job, {})

    assert repaired is not None
    assert repaired["name"] == "spontaneous_line"
    assert repaired["target_sim_id"] is None
    assert repaired["args"]["text"] == "hello"


def test_repair_speech_without_text_is_dropped():
    intent = {"name": "say_to", "kind": "speak", "args": {}, "params": {}}
    assert graph._repair_intent(intent, make_job(), {}) is None


def test_repair_leaves_non_speech_intent_alone():
    intent = {"name": "set_mood", "kind": "set_mood", "args": {"reason": "x"}, "params": {}}
    assert graph._repair_intent(intent, make_job(), {}) is intent


def test_annotate_speech_marks_out_of_range_line_unsurfaced(monkeypatch):
    policy = SpeechPolicy()
    policy.hearing_radius = 5.0
    monkeypatch.setattr(graph, "_agency", SimpleNamespace(speech=policy))
    world = {
        "active_sim_id": 1,
        "sims": {
            "1": {"sim_id": 1, "location": "0.0,0.0"},
            "2": {"sim_id": 2, "location": "100.0,100.0", "interaction_target_sim_id": 1},
        },
    }
    intents = [
        {"id": "x", "sim_id": 2, "kind": "speak", "name": "say_to", "target_sim_id": 1,
         "args": {}, "params": {}}
    ]

    graph._annotate_speech(
        intents, job_kind="reaction", world=world,
        player_id="local", save_id="save1", lang="en",
    )

    assert intents[0]["params"]["surfaced"] is False
    assert intents[0]["speech_kind"] == "reaction"


def test_annotate_speech_surfaces_a_near_directed_line(monkeypatch):
    policy = SpeechPolicy()
    policy.hearing_radius = 20.0
    monkeypatch.setattr(graph, "_agency", SimpleNamespace(speech=policy))
    world = {
        "active_sim_id": 1,
        "sims": {
            "1": {"sim_id": 1, "location": "0.0,0.0"},
            "2": {"sim_id": 2, "location": "1.0,1.0", "interaction_target_sim_id": 1},
        },
    }
    intents = [
        {"id": "x", "sim_id": 2, "kind": "speak", "name": "say_to", "target_sim_id": 1,
         "args": {}, "params": {}}
    ]

    graph._annotate_speech(
        intents, job_kind="social", world=world,
        player_id="local", save_id="save1", lang="en",
    )

    assert intents[0]["params"]["surfaced"] is True
    assert intents[0]["speech_kind"] == "directed"


def test_annotate_speech_rejects_wrong_language(monkeypatch):
    policy = SpeechPolicy()
    monkeypatch.setattr(graph, "_agency", SimpleNamespace(speech=policy))
    world = {
        "active_sim_id": 1,
        "sims": {
            "1": {"sim_id": 1, "location": "0.0,0.0"},
            "2": {"sim_id": 2, "location": "1.0,1.0"},
        },
    }
    text = "This snapshot shows me feeling happy today."
    intents = [
        {"id": "x", "sim_id": 2, "kind": "speak", "name": "spontaneous_line",
         "target_sim_id": None, "args": {"text": text}, "params": {"text": text}}
    ]

    graph._annotate_speech(
        intents, job_kind="idle", world=world,
        player_id="local", save_id="save1", lang="pt-BR",
    )

    assert intents[0]["speech_lang_rejected"] is True
    assert intents[0]["params"]["surfaced"] is False


def test_annotate_speech_keeps_matching_language(monkeypatch):
    policy = SpeechPolicy()
    monkeypatch.setattr(graph, "_agency", SimpleNamespace(speech=policy))
    world = {"active_sim_id": 1, "sims": {"1": {"sim_id": 1, "location": "0.0,0.0"}}}
    text = "O cheiro de café está ótimo hoje."
    intents = [
        {"id": "x", "sim_id": 1, "kind": "speak", "name": "spontaneous_line",
         "target_sim_id": None, "args": {"text": text}, "params": {"text": text}}
    ]

    graph._annotate_speech(
        intents, job_kind="idle", world=world,
        player_id="local", save_id="save1", lang="pt-BR",
    )

    assert "speech_lang_rejected" not in intents[0]
