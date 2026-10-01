"""Tests for the v0.4 P4/P4b conversation sessions (``agent.conversations``)."""

from __future__ import annotations

from sensewright_sidecar.agent.conversations import ConversationManager, Session
from sensewright_sidecar.agent.social import Dialogue
from sensewright_sidecar.config import AgentsConfig, ConversationsConfig, Settings


class FakeClock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _dialogue(a=1, b=2, text_a="Hi", text_b="Hey", tone="friendly", topic="chat"):
    return Dialogue(
        a=a,
        b=b,
        lines=[
            {"speaker": "a", "text": text_a, "tone": tone},
            {"speaker": "b", "text": text_b, "tone": tone},
        ],
        topic=topic,
        source="template",
    )


def test_record_accumulates_and_closes_at_max_turns():
    manager = ConversationManager(
        Settings(agents=AgentsConfig(conversations=ConversationsConfig(max_turns=4)))
    )
    assert manager.record(_dialogue(), a_name="Ana", b_name="Bob") is None
    assert manager.is_active(1, 2) is True
    closed = manager.record(_dialogue(text_a="Again", text_b="Sure"))
    assert isinstance(closed, Session)
    assert closed.turns == 4
    assert closed.a_name == "Ana" and closed.b_name == "Bob"
    assert closed.topic == "chat"
    assert manager.is_active(1, 2) is False
    assert manager.snapshot()["completed"] == 1


def test_summary_line_is_localized_and_uses_names():
    manager = ConversationManager()
    session = Session(a=1, b=2, topic="gardening", tone="friendly", a_name="Ana", b_name="Bob")
    en = manager.summary_line(session, lang="en")
    assert "Ana" in en and "Bob" in en and "gardening" in en
    pt = manager.summary_line(session, lang="pt-BR")
    assert "Ana" in pt and "Bob" in pt


def test_summary_line_leave_uses_goodbye_template():
    manager = ConversationManager()
    session = Session(a=1, b=2, a_name="Ana", b_name="Bob")
    text = manager.summary_line(session, lang="en", leaving=True)
    assert "Ana" in text and "Bob" in text
    assert "left" in text.lower() or "company" in text.lower()


def test_sweep_closes_inactive_sessions():
    clock = FakeClock()
    manager = ConversationManager(clock=clock)
    manager.record(_dialogue(), a_name="Ana", b_name="Bob")
    assert manager.is_active(1, 2) is True

    closed = manager.sweep(set())
    assert len(closed) == 1
    assert manager.is_active(1, 2) is False


def test_sweep_keeps_active_sessions():
    clock = FakeClock()
    manager = ConversationManager(clock=clock)
    manager.record(_dialogue())
    closed = manager.sweep({frozenset({1, 2})})
    assert closed == []
    assert manager.is_active(1, 2) is True


def test_sweep_does_not_close_a_session_waiting_for_pair_cooldown():
    """idle_seconds must exceed the pair cooldown so a session is not cut short."""
    settings = Settings(
        agents=AgentsConfig(
            conversations=ConversationsConfig(idle_seconds=300.0),
        )
    )
    clock = FakeClock()
    manager = ConversationManager(settings, clock=clock)
    manager.record(_dialogue())
    clock.advance(180.0)
    # Still active (interaction ongoing) and within idle window.
    assert manager.sweep({frozenset({1, 2})}) == []


async def test_summarize_falls_back_without_registry():
    manager = ConversationManager()
    session = Session(a=1, b=2, topic="books", tone="casual", a_name="Ana", b_name="Bob")
    text = await manager.summarize(session, lang="en")
    assert "Ana" in text and "Bob" in text
