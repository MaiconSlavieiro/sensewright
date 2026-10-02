"""Regression test: the mod's active language must drive t() lookups.

`set_language()` stores the active locale, but `t()` calls
`resolve_locale(None)`. If that falls straight through to the manifest default,
every string renders in the default locale and game-language detection has no
effect (the original bug). This loads the real mod i18n engine with a stubbed
`sims4` module and asserts the active language wins.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MOD_ROOT = REPO_ROOT / "mod"


@pytest.fixture()
def mod_i18n():
    # Stub the game-only modules the mod's debug_log imports.
    sims4 = types.ModuleType("sims4")
    sims4_log = types.ModuleType("sims4.log")

    class _Logger:
        def __init__(self, *args, **kwargs):
            pass

        def info(self, *args, **kwargs):
            pass

        def debug(self, *args, **kwargs):
            pass

        def warn(self, *args, **kwargs):
            pass

        def error(self, *args, **kwargs):
            pass

        def exception(self, *args, **kwargs):
            pass

    sims4_log.Logger = _Logger
    sims4.log = sims4_log
    sys.modules.setdefault("sims4", sims4)
    sys.modules.setdefault("sims4.log", sims4_log)

    sys.path.insert(0, str(MOD_ROOT))
    for name in [n for n in list(sys.modules) if n.startswith("sensewright_mod")]:
        del sys.modules[name]

    import sensewright_mod.i18n as mod_i18n  # noqa: E402

    yield mod_i18n

    if str(MOD_ROOT) in sys.path:
        sys.path.remove(str(MOD_ROOT))


def test_active_language_overrides_default(mod_i18n):
    engine = mod_i18n.get_engine()
    assert engine.set_language("pt-BR")
    assert engine.resolve_locale(None) == "pt-BR"
    # en-US "Refresh" vs pt-BR "Atualizar"
    assert mod_i18n.t("panel.btn.refresh") == "Atualizar"


def test_switching_back_to_default(mod_i18n):
    engine = mod_i18n.get_engine()
    engine.set_language("pt-BR")
    assert mod_i18n.t("panel.btn.refresh") == "Atualizar"
    engine.set_language("en-US")
    assert mod_i18n.t("panel.btn.refresh") == "Refresh"
