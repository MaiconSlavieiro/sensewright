"""
Tests for the God UI helpers and the God wire client (offline).
No game and no network: http_client is monkeypatched.

Run with the system Python (3.10+).
"""

import os
import sys

# Add mod directory to path
mod_dir = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, mod_dir)

import pytest

from sensewright_mod import debug_log, god_ui, http_client, i18n, integrations


@pytest.fixture(autouse=True)
def _reset_locale_and_guard():
    i18n.set_locale("en")
    god_ui.reset_onboarding_guard()
    yield
    god_ui.reset_onboarding_guard()
    i18n.set_locale("en")


def _capture_post(monkeypatch):
    captured = {}

    def fake_post(path, payload, timeout=http_client.DEFAULT_TIMEOUT):
        captured["path"] = path
        captured["payload"] = payload
        return {"ok": True}

    monkeypatch.setattr(http_client, "post_json", fake_post)
    return captured


# --- pure helpers ---

def test_build_onboarding_request_existing_values():
    request = god_ui.build_onboarding_request(
        {
            "mood_tags": ["novela", "bogus"],
            "free_text": "old",
            "mood_influence": 0.8,
            "configured": False,
        },
        "new text",
    )

    assert request["mood_tags"] == ["novela"]
    assert request["free_text"] == "new text"
    assert request["mood_influence"] == 0.8
    for key in ("title", "body", "placeholder", "ok", "cancel"):
        assert request[key]


def test_build_onboarding_request_defaults():
    request = god_ui.build_onboarding_request(None)

    assert request["mood_tags"] == []
    assert request["free_text"] == ""
    assert request["mood_influence"] == 0.5
    assert request["placeholder"] == i18n.t("god.zeitgeist.prompt_placeholder")


def test_build_onboarding_request_keeps_stored_text_and_clamps():
    request = god_ui.build_onboarding_request(
        {"free_text": "stored", "mood_influence": 9.0})
    assert request["free_text"] == "stored"
    assert request["mood_influence"] == 1.0

    request = god_ui.build_onboarding_request({"mood_influence": "bad"})
    assert request["mood_influence"] == 0.5


def test_format_controls_renders_labels_values_and_options():
    controls = [
        {
            "key": "chaos_degree",
            "kind": "slider",
            "label_key": "god.control.chaos_degree.label",
            "description_key": "god.control.chaos_degree.desc",
            "default": 0.3,
        },
        {
            "key": "power_gossip",
            "kind": "toggle",
            "label_key": "god.control.power_gossip.label",
            "description_key": "god.control.power_gossip.desc",
            "default": True,
        },
        {
            "key": "evolution_speed",
            "kind": "select",
            "label_key": "god.control.evolution_speed.label",
            "default": "normal",
            "options": [{"value": "slow", "label_key": "god.speed.slow"}],
        },
    ]

    text = god_ui.format_controls(controls, {"chaos_degree": 0.6})

    assert i18n.t("god.control.chaos_degree.label") in text
    assert i18n.t("god.control.power_gossip.label") in text
    assert i18n.t("god.speed.slow") in text
    assert "0.6" in text


def test_format_controls_empty_and_malformed():
    assert god_ui.format_controls([]) == ""
    assert god_ui.format_controls(None) == ""

    text = god_ui.format_controls([None, {}, "x", {"key": "chaos_degree"}])
    assert isinstance(text, str)


# --- public flow (offline, never raises) ---

def test_maybe_show_onboarding_console_without_sidecar(monkeypatch):
    def boom(*args, **kwargs):
        raise http_client.SidecarUnreachable()

    monkeypatch.setattr(god_ui.http_client, "get_zeitgeist", boom)

    result = god_ui.maybe_show_zeitgeist_onboarding(None)
    assert result == "console"

    # Guard flag: a second call in the same session is a no-op.
    assert god_ui.maybe_show_zeitgeist_onboarding(None) is False


def test_maybe_show_onboarding_skips_configured(monkeypatch):
    monkeypatch.setattr(
        god_ui.http_client, "get_zeitgeist",
        lambda *args, **kwargs: {"ok": True,
                                 "zeitgeist": {"configured": True}},
    )

    assert god_ui.maybe_show_zeitgeist_onboarding(None) is False


def test_onboarding_applies_choice_when_dialog_shown(monkeypatch):
    monkeypatch.setattr(
        god_ui.http_client, "get_zeitgeist",
        lambda *args, **kwargs: {"ok": True,
                                 "zeitgeist": {"configured": False}},
    )
    captured = {}

    def fake_set(sim, mood_tags, free_text, mood_influence, lang=None):
        captured["sim"] = sim
        captured["mood_tags"] = mood_tags
        captured["mood_influence"] = mood_influence
        captured["lang"] = lang
        return {"ok": True}

    monkeypatch.setattr(god_ui.http_client, "set_zeitgeist", fake_set)
    monkeypatch.setattr(
        god_ui, "_show_ok_cancel",
        lambda sim_info, title, text, on_ok: (on_ok(), True)[1],
    )

    result = god_ui.maybe_show_zeitgeist_onboarding(
        {"sim_id": 7, "save_id": "s1"})

    assert result == "dialog"
    assert captured["sim"]["sim_id"] == 7
    assert captured["mood_tags"] == []
    assert captured["mood_influence"] == 0.5
    assert captured["lang"] == "en"


def test_prompt_household_background_console_without_dialog(monkeypatch):
    monkeypatch.setattr(god_ui, "_show_ok_cancel", lambda *a, **k: False)

    result = god_ui.prompt_household_background(None, household_id=5)
    assert result == "console"


def test_prompt_household_background_requests_when_dialog_shown(monkeypatch):
    captured = {}

    def fake_request(sim, scope="sim", household_id=None, player_hints="",
                     census=None, force=False, lang="en"):
        captured.update({
            "sim": sim,
            "scope": scope,
            "household_id": household_id,
            "player_hints": player_hints,
            "census": census,
            "lang": lang,
        })
        return {"ok": True}

    monkeypatch.setattr(god_ui.http_client, "request_background", fake_request)
    monkeypatch.setattr(
        god_ui, "_show_ok_cancel",
        lambda sim_info, title, text, on_ok: (on_ok(), True)[1],
    )

    result = god_ui.prompt_household_background(
        {"sim_id": 8, "save_id": "s1"}, household_id=12, census={"sims": []})

    assert result == "dialog"
    assert captured["scope"] == "household"
    assert captured["household_id"] == 12
    assert captured["census"] == {"sims": []}
    assert captured["lang"] == "en"


def test_sim_ref_from_dict_and_object():
    ref = god_ui._sim_ref({"player_id": "p", "save_id": "s", "sim_id": 3,
                           "household_id": 44})
    assert ref["sim_id"] == 3
    assert ref["household_id"] == 44

    class FakeSim(object):
        id = 9
        household = None

    ref = god_ui._sim_ref(FakeSim())
    assert ref["sim_id"] == 9
    assert ref["player_id"] == "local"


# --- wire bodies for the new http_client functions ---

def test_get_zeitgeist_query(monkeypatch):
    captured = {}

    def fake_get(path, timeout=http_client.DEFAULT_TIMEOUT):
        captured["path"] = path
        return {"ok": True}

    monkeypatch.setattr(http_client, "get_json", fake_get)

    result = http_client.get_zeitgeist("save-1", "local")

    assert result == {"ok": True}
    assert captured["path"] == "/v1/god/zeitgeist?save_id=save-1&player_id=local"


def test_set_zeitgeist_body(monkeypatch):
    captured = _capture_post(monkeypatch)
    sim = {"player_id": "local", "save_id": "s", "sim_id": 1}

    http_client.set_zeitgeist(sim, ["novela"], "free", 0.7, "pt-BR")

    assert captured["path"] == "/v1/god/zeitgeist"
    assert captured["payload"] == {
        "sim": sim,
        "mood_tags": ["novela"],
        "free_text": "free",
        "mood_influence": 0.7,
        "lang": "pt-BR",
    }


def test_suggest_zeitgeist_body(monkeypatch):
    captured = _capture_post(monkeypatch)
    sim = {"sim_id": 2}

    http_client.suggest_zeitgeist(sim, ["caos"], "hint", "en")

    assert captured["path"] == "/v1/god/zeitgeist/suggest"
    assert captured["payload"] == {
        "sim": sim,
        "mood_tags": ["caos"],
        "free_text": "hint",
        "lang": "en",
    }


def test_request_background_body(monkeypatch):
    captured = _capture_post(monkeypatch)
    sim = {"sim_id": 3}
    census = {"sims": [], "households": []}

    http_client.request_background(sim, scope="household", household_id=9,
                                   player_hints="hi", census=census, force=True,
                                   lang="pt-BR")

    assert captured["path"] == "/v1/god/background"
    assert captured["payload"] == {
        "sim": sim,
        "scope": "household",
        "household_id": 9,
        "player_hints": "hi",
        "census": census,
        "force": True,
        "queue": False,
        "lang": "pt-BR",
    }


def test_request_background_defaults(monkeypatch):
    captured = _capture_post(monkeypatch)

    http_client.request_background({"sim_id": 4})

    assert captured["payload"] == {
        "sim": {"sim_id": 4},
        "scope": "sim",
        "household_id": None,
        "player_hints": "",
        "census": None,
        "force": False,
        "queue": False,
        "lang": "en",
    }


def test_get_god_controls_endpoint(monkeypatch):
    captured = {}

    def fake_get(path, timeout=http_client.DEFAULT_TIMEOUT):
        captured["path"] = path
        return {"ok": True, "controls": [], "values": {}}

    monkeypatch.setattr(http_client, "get_json", fake_get)

    http_client.get_god_controls()

    assert captured["path"] == "/v1/god/controls"


def test_send_census_body(monkeypatch):
    captured = _capture_post(monkeypatch)
    sim = {"sim_id": 5}
    sims = [{"sim_id": 5}]
    households = [{"household_id": 1}]

    http_client.send_census(sim, sims, households, scope="active_zone",
                            lang="en")

    assert captured["path"] == "/v1/census"
    assert captured["payload"] == {
        "sim": sim,
        "scope": "active_zone",
        "sims": sims,
        "households": households,
        "lang": "en",
    }


# --- H5 / M6 / L8: shared guard, localized hints, debug-log fallback ---

def test_safe_getattr_is_the_shared_logger():
    """H5: god_ui uses the shared guarded getattr (which logs)."""
    assert god_ui._safe_getattr is debug_log.safe_getattr
    assert god_ui._safe_call is debug_log.safe_call


def test_safe_getattr_returns_default_on_error():
    class Boom(object):
        @property
        def bad(self):
            raise RuntimeError("nope")

    assert god_ui._safe_getattr(Boom(), "bad", "default") == "default"


def test_zeitgeist_console_hint_is_localized(monkeypatch):
    """M6: the console fallback is built through i18n keys."""
    captured = {}
    monkeypatch.setattr(
        god_ui.http_client, "get_zeitgeist",
        lambda *a, **k: {"ok": True, "zeitgeist": {"configured": False}})
    monkeypatch.setattr(god_ui, "_show_ok_cancel", lambda *a, **k: False)
    monkeypatch.setattr(
        god_ui, "_output_hint",
        lambda message: captured.update(msg=message) or True)

    result = god_ui.maybe_show_zeitgeist_onboarding(None)

    assert result == "console"
    assert i18n.t("god.zeitgeist.title") in captured["msg"]
    assert "sw.zeitgeist" in captured["msg"]


def test_background_console_hint_is_localized(monkeypatch):
    captured = {}
    monkeypatch.setattr(god_ui, "_show_ok_cancel", lambda *a, **k: False)
    monkeypatch.setattr(
        god_ui, "_output_hint",
        lambda message: captured.update(msg=message) or True)

    result = god_ui.prompt_household_background(None, household_id=5)

    assert result == "console"
    assert i18n.t("god.background.title") in captured["msg"]
    assert i18n.t("god.background.prompt_placeholder") in captured["msg"]


def test_output_hint_falls_back_to_debug_log(monkeypatch):
    """L8: the non-UI fallback writes to the debug log, not stdout."""
    logged = []
    monkeypatch.setattr(
        god_ui, "debug_log", lambda message: logged.append(message))

    assert god_ui._output_hint("hello") is True
    assert any("hello" in message for message in logged)


def test_show_ok_cancel_prefers_s4cl(monkeypatch):
    sentinel = object()
    captured = {}
    monkeypatch.setattr(integrations, "s4cl_ok_cancel", lambda title, text: sentinel)

    def fake_show(dialog, sim_info=None, on_confirm=None, on_cancel=None):
        captured["dialog"] = dialog
        captured["on_confirm"] = on_confirm
        return True

    monkeypatch.setattr(integrations, "s4cl_show_ok_cancel", fake_show)
    called = []
    monkeypatch.setattr(god_ui, "_try_import_dialog_class",
                        lambda: (_ for _ in ()).throw(AssertionError("native")))

    assert god_ui._show_ok_cancel(None, "t", "d", lambda: called.append(True)) is True
    assert captured["dialog"] is sentinel
    captured["on_confirm"]()
    assert called == [True]


def test_show_ok_cancel_falls_back_when_s4cl_absent(monkeypatch):
    monkeypatch.setattr(integrations, "s4cl_ok_cancel", lambda title, text: None)
    monkeypatch.setattr(god_ui, "_try_import_dialog_class", lambda: None)

    assert god_ui._show_ok_cancel(None, "t", "d", lambda: None) is False


def test_localize_delegates_to_stack_seam():
    # Offline the seam returns the plain string unchanged.
    assert god_ui._localize("hello") == "hello"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
