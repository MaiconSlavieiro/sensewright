"""
Offline tests for the in-game configuration panel (``panel_ui``).

The grouping/rendering helpers are pure and must never raise on malformed input.
``set_value`` is checked against a monkeypatched http_client so no network runs.

Run with the system Python (3.10+).
"""

import os
import sys

mod_dir = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, mod_dir)

from sensewright_mod import i18n, panel_ui  # noqa: E402


def _reset_locale():
    i18n.set_locale("en")


def test_section_of_uses_first_key_segment():
    assert panel_ui.section_of({"key": "agents.impulse_frequency"}) == "agents"
    assert panel_ui.section_of({"key": "god"}) == "god"
    assert panel_ui.section_of({}) == "general"


def test_group_sections_orders_and_buckets():
    _reset_locale()
    controls = [
        {"key": "llm.temperature"},
        {"key": "god.autonomy_degree"},
        {"key": "agents.agent_seats"},
        {"key": "god.chaos_degree"},
        {"not": "a dict control"},  # ignored by group_sections? it's a dict w/o key
    ]
    sections = panel_ui.group_sections(controls)
    ids = [s["id"] for s in sections]
    # Known sections come first in SECTION_ORDER: god before agents before llm.
    assert ids == ["god", "agents", "llm", "general"]
    god = sections[0]
    assert len(god["controls"]) == 2


def test_group_sections_handles_malformed():
    assert panel_ui.group_sections(None) == []
    assert panel_ui.group_sections("nope") == []


def test_section_label_localized_and_fallback():
    _reset_locale()
    assert panel_ui.section_label("god") == "God"
    # Unknown id falls back to a title-cased name, not the raw key.
    assert panel_ui.section_label("mystery") == "Mystery"


def test_format_home_lists_sections():
    _reset_locale()
    sections = panel_ui.group_sections([{"key": "god.autonomy_degree"}])
    text = panel_ui.format_home(sections)
    assert "God" in text


def test_set_value_calls_sidecar(monkeypatch):
    captured = {}

    def _fake_set_god_controls(**kwargs):
        captured.update(kwargs)
        return {}

    monkeypatch.setattr(panel_ui.http_client, "set_god_controls", _fake_set_god_controls)
    assert panel_ui.set_value("god.autonomy_degree", 0.5) is True
    assert captured["values"] == {"god.autonomy_degree": 0.5}


def test_set_value_empty_key_is_false():
    assert panel_ui.set_value("", 1) is False
