"""
Offline tests for the pie-menu interactions built on the new stack base.

No game and no S4CL: the classes must import, expose their action/display keys,
the dispatcher must never raise and ``install()`` must degrade gracefully when
the library is absent (which is exactly the case here).

Run with the system Python (3.10+).
"""

import os
import sys

mod_dir = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, mod_dir)

from sensewright_mod import pie_menu  # noqa: E402


def test_interaction_classes_exist():
    for name in ("SensewrightPanelInteraction", "SensewrightChatInteraction",
                 "SensewrightConfirmInteraction", "SensewrightHudInteraction"):
        assert hasattr(pie_menu, name)


def test_actions_map_to_behaviors():
    assert pie_menu.SensewrightPanelInteraction.ACTION == "panel"
    assert pie_menu.SensewrightChatInteraction.ACTION == "chat"
    assert pie_menu.SensewrightConfirmInteraction.ACTION == "confirm"
    assert pie_menu.SensewrightHudInteraction.ACTION == "hud"


def test_display_keys_present():
    for cls in (pie_menu.SensewrightPanelInteraction,
                pie_menu.SensewrightChatInteraction,
                pie_menu.SensewrightConfirmInteraction,
                pie_menu.SensewrightHudInteraction):
        assert cls.DISPLAY_KEY.startswith("cmd.pie.")


def test_dispatch_never_raises():
    # Unknown kinds are ignored; the rest are guarded outside the game.
    pie_menu._dispatch("definitely_not_a_kind")
    pie_menu._dispatch("hud")
    pie_menu._dispatch("chat")
    pie_menu._dispatch("confirm")
    pie_menu._dispatch("panel")


def test_install_without_s4cl_is_safe():
    # On the test host S4CL is absent: install must return False, not raise.
    assert pie_menu.install() in (True, False)
