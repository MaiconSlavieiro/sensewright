"""
Offline tests for the pie-menu spike: the interaction classes and the pure-Python
package builder (`build_package.py`). No game, no network.

Run with the system Python (3.10+).
"""

import os
import sys

# Add the mod directory (for sensewright_mod and build_package) to path.
mod_dir = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, mod_dir)

import pytest

from sensewright_mod import pie_menu


def test_interaction_classes_exist():
    for name in ("SensewrightPanelInteraction", "SensewrightChatInteraction",
                 "SensewrightConfirmInteraction", "SensewrightHudInteraction"):
        assert hasattr(pie_menu, name)


def test_actions_map_to_behaviors():
    assert pie_menu.SensewrightPanelInteraction.ACTION == "panel"
    assert pie_menu.SensewrightChatInteraction.ACTION == "chat"
    assert pie_menu.SensewrightConfirmInteraction.ACTION == "confirm"
    assert pie_menu.SensewrightHudInteraction.ACTION == "hud"


def test_dispatch_never_raises():
    # Unknown kinds are ignored; the rest are guarded outside the game.
    pie_menu._dispatch("definitely_not_a_kind")
    pie_menu._dispatch("hud")
    pie_menu._dispatch("chat")
    pie_menu._dispatch("confirm")


def test_dialogs_import_and_are_guarded():
    from sensewright_mod import dialogs

    # No game/owner here: both must return False, never raise.
    assert dialogs.prompt_text(None, "t", "b") is False
    assert dialogs.confirm(None, "t", "b") is False


# --- package builder ---

def test_package_resources_unique_and_typed():
    import build_package

    resources = build_package.package_resources()
    types = {resource[1] for resource in resources}
    assert build_package.INTERACTION_TUNING_TYPE in types
    assert build_package.STRING_TABLE_TYPE in types

    instances = [resource[3] for resource in resources]
    assert len(instances) == len(set(instances))


def test_package_instances_match_tuning_xml():
    import build_package

    xml_instances = {resource[3] for resource in build_package.interaction_resources()}
    assert len(xml_instances) == 4


def test_build_stbl_header():
    import build_package

    data = build_package.build_stbl({0xA1400001: "Open Panel"})
    assert data[:4] == b"STBL"


def test_build_package_writes_dbpf(tmp_path):
    import build_package

    target = tmp_path / "Sensewright.package"
    build_package.build_package(target)
    raw = target.read_bytes()
    assert raw[:4] == b"DBPF"
    assert len(raw) > 200


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
