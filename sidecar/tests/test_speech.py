"""Tests for the v0.4 P1 SpeechPolicy (``agent.speech``)."""

from __future__ import annotations

from sensewright_sidecar.agent.speech import (
    DIRECTED,
    INNER_THOUGHT,
    MURMUR,
    REACTION,
    SpeechPolicy,
)
from sensewright_sidecar.config import AgentsConfig, Settings, SpeechConfig


class FakeRng:
    def __init__(self, value: float) -> None:
        self.value = value

    def random(self) -> float:
        return self.value


class FakeClock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_classify_directed_reaction_murmur_and_inner():
    assert SpeechPolicy.classify(job_kind="idle", has_target=True, intent_kind="speak") == DIRECTED
    assert SpeechPolicy.classify(job_kind="reaction", has_target=False) == REACTION
    assert SpeechPolicy.classify(job_kind="idle", has_target=False, intent_kind="speak") == MURMUR
    assert SpeechPolicy.classify(job_kind="idle", has_target=False) == MURMUR


def test_inner_thought_is_never_surfaced():
    policy = SpeechPolicy()
    assert policy.should_surface("s:1", kind=INNER_THOUGHT) is False
    assert policy.snapshot()["thoughts"] == 1


def test_within_hearing_radius_and_zero_disables(): 
    policy = SpeechPolicy()
    policy.hearing_radius = 5.0
    assert policy.within_hearing(3.0) is True
    assert policy.within_hearing(9.0) is False
    assert policy.within_hearing(None) is True
    policy.hearing_radius = 0.0
    assert policy.within_hearing(999.0) is True


def test_directed_surface_respects_distance():
    policy = SpeechPolicy()
    policy.hearing_radius = 5.0
    assert policy.should_surface("s:1", kind=DIRECTED, distance=2.0) is True
    assert policy.should_surface("s:2", kind=DIRECTED, distance=50.0) is False


def test_cadence_min_interval_blocks_a_second_line():
    clock = FakeClock()
    policy = SpeechPolicy(clock=clock)
    assert policy.should_surface("s:1", kind=DIRECTED, now=0.0) is True
    policy.note("s:1", kind=DIRECTED, now=0.0)
    assert policy.should_surface("s:1", kind=DIRECTED, now=5.0) is False
    assert policy.should_surface("s:1", kind=DIRECTED, now=999.0) is True


def test_murmur_needs_notify_thoughts_and_chance():
    policy = SpeechPolicy(rng=FakeRng(0.01))
    policy.ambient_talk_chance = 0.5
    assert policy.should_surface("s:1", kind=MURMUR, now=0.0) is True

    policy2 = SpeechPolicy(rng=FakeRng(0.9))
    policy2.ambient_talk_chance = 0.5
    assert policy2.should_surface("s:1", kind=MURMUR, now=0.0) is False

    policy3 = SpeechPolicy(rng=FakeRng(0.0))
    policy3.notify_thoughts = False
    assert policy3.should_surface("s:1", kind=MURMUR, now=0.0) is False


def test_murmur_cooldown_blocks_repeats():
    policy = SpeechPolicy(rng=FakeRng(0.0))
    policy.ambient_talk_chance = 1.0
    policy.min_interval = 0.0
    assert policy.should_surface("s:1", kind=MURMUR, now=0.0) is True
    policy.note("s:1", kind=MURMUR, now=0.0)
    assert policy.should_surface("s:1", kind=MURMUR, now=1.0) is False


def test_configure_reads_speech_block():
    settings = Settings(
        agents=AgentsConfig(
            speech=SpeechConfig(
                hearing_radius=7.5,
                ambient_talk_chance=0.2,
                notify_thoughts=False,
                min_interval_between_lines=12.0,
            )
        )
    )
    policy = SpeechPolicy(settings)
    assert policy.hearing_radius == 7.5
    assert policy.ambient_talk_chance == 0.2
    assert policy.notify_thoughts is False
    assert policy.min_interval == 12.0
    assert set(policy.snapshot()) >= {"surfaced", "suppressed", "murmurs"}
