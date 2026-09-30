"""
Offline tests for the third-party stack integration layer (``integrations``).

On the test host neither Lot 51 Core nor S4CL is installed, so every helper must
degrade to ``None``/``False`` and never raise. These lock in that contract.

Run with the system Python (3.10+).
"""

import os
import sys

mod_dir = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, mod_dir)

from sensewright_mod import integrations  # noqa: E402


def test_refresh_never_raises():
    result = integrations.refresh()
    assert set(result.keys()) == {"lot51", "s4cl"}


def test_stack_summary_shape():
    summary = integrations.stack_summary()
    assert summary.startswith("stack:")
    assert "lot51=" in summary and "s4cl=" in summary


def test_lot51_helpers_are_safe_without_lib():
    handler, core_event = integrations.lot51_events()
    # No library on the host: both are None and nothing raises.
    assert handler is None
    assert core_event is None
    assert integrations.lot51_register(None, lambda *a, **k: None) is False
    assert integrations.lot51_register_service(None) is False
    assert integrations.lot51_service_manager() is None


def test_s4cl_helpers_are_safe_without_lib():
    assert integrations.s4cl_notification("t", "d") is None
    assert integrations.s4cl_show_notification(None) is False
    assert integrations.s4cl_ok_cancel("t", "d") is None
    assert integrations.s4cl_show_ok_cancel(None) is False
    assert integrations.s4cl_interaction_base() is None
    assert integrations.s4cl_register_interaction(None) is False


def test_native_localized_string_returns_input_offline():
    # Outside the game there is no LocalizationHelperTuning: identity.
    assert integrations.native_localized_string("hello") == "hello"
