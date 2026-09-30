"""
Offline tests for the P0 native-dialog spike (``ui_probe``).

No game and no UI: the probes must always return a diagnostics dict and never
raise, even when every game import fails (which is exactly the case here).

Run with the system Python (3.10+).
"""

import os
import sys

# Add mod directory to path
mod_dir = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, mod_dir)

import pytest

from sensewright_mod import i18n, ui_probe


@pytest.fixture(autouse=True)
def _reset_locale():
    i18n.set_locale("en")
    yield
    i18n.set_locale("en")


def test_kinds_and_default():
    for kind in ("notification", "okcancel", "picker", "picker_icons",
                 "picker_text", "dropdown", "labeled_icons", "info_columns",
                 "response", "input", "multi", "panel", "panel_home", "pie"):
        assert kind in ui_probe.KINDS
    assert ui_probe.DEFAULT_KIND in ui_probe.KINDS


def test_run_unknown_kind_returns_none():
    assert ui_probe.run("does_not_exist") is None


def test_run_never_raises_without_game():
    for kind in ui_probe.KINDS:
        result = ui_probe.run(kind, None)
        assert isinstance(result, dict)
        assert result["kind"] == kind
        assert result["layer"]
        # No game here: every probe must report failure, not crash.
        assert result["ok"] is False


def test_run_all_covers_every_kind_in_order():
    results = ui_probe.run_all(None)
    assert [item["kind"] for item in results] == list(ui_probe.KINDS)


def test_result_coerces_error_to_text():
    result = ui_probe._result("picker", True, "dialog", None)
    assert result == {"kind": "picker", "ok": True, "layer": "dialog", "error": None}

    result = ui_probe._result("picker", False, "build", ValueError("boom"))
    assert result["error"] == "boom"


def test_format_result_is_localized():
    text = ui_probe.format_result(
        {"kind": "picker", "ok": False, "layer": "import", "error": "boom"})
    assert "picker" in text
    assert "import" in text
    assert "boom" in text
    assert ui_probe.format_result(None) == ""


def test_inspect_reports_every_candidate():
    lines = ui_probe.inspect()
    assert len(lines) == len(ui_probe._CANDIDATES)
    assert all(isinstance(line, str) for line in lines)


def test_format_report_is_string():
    report = ui_probe.format_report()
    assert isinstance(report, str)
    assert report


def test_is_resource_key():
    class _Key(object):
        type = 1
        group = 2
        instance = 3

    assert ui_probe._is_resource_key(_Key())
    assert not ui_probe._is_resource_key(None)
    assert not ui_probe._is_resource_key(object())


def test_icon_pool_empty_without_game():
    assert ui_probe._icon_pool(None) == []


def test_format_value():
    assert ui_probe._format_value(True) == i18n.t("cmd.panel.value.on")
    assert ui_probe._format_value(False) == i18n.t("cmd.panel.value.off")
    assert ui_probe._format_value(0.5) == "0.5"
    assert ui_probe._format_value(12) == "12"
    assert ui_probe._format_value(["a", "b"]) == "a,b"
    assert ui_probe._format_value(None) == ""


def test_panel_inventory_is_well_formed():
    kinds = set()
    for section in ui_probe._PANEL_SECTIONS:
        assert section["key"]
        assert ui_probe.i18n.t(section["title"]) != section["title"]
        for setting in section["settings"]:
            assert setting["key"]
            assert setting["kind"] in ("slider", "select", "toggle", "tags", "number")
            kinds.add(setting["kind"])
    assert {"slider", "select", "toggle", "tags", "number"} <= kinds


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
