"""Regression test: every UI key used by the in-game mod resolves.

The mod calls ``i18n.t('panel.title')``, ``t('chat.title', ...)`` etc. A typo or
a missing key silently renders as ``[missing:key]`` in-game, which is exactly the
class of bug this test guards against.

It scans ``mod/sensewright_mod/*.py`` for literal ``t('...')`` calls and verifies
each key resolves against the *bundled mod locales*, using the same engine the
runtime uses. It also asserts en-US / pt-BR key parity for the mod bundle.
"""
from __future__ import annotations

import re
from pathlib import Path

from sensewright_sidecar.i18n_engine import I18nEngine

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MOD_DIR = REPO_ROOT / "mod" / "sensewright_mod"
MOD_LOCALES = MOD_DIR / "locales"

# Matches module-level ``t('key')`` / ``t("key")`` but not method calls ``.t(``.
_T_CALL_RE = re.compile(r"(?<![.\w])t\(\s*['\"]([A-Za-z0-9_.]+)['\"]")


def _mod_engine() -> I18nEngine:
    # Overlay dir intentionally points at a non-existent path so only bundle
    # locales are consulted (mirrors a clean install).
    return I18nEngine(
        bundle_dir=MOD_LOCALES,
        overlay_dir=MOD_LOCALES / "__no_overlay__",
    )


def _used_keys() -> set:
    keys = set()
    for py_file in MOD_DIR.glob("*.py"):
        if py_file.name in {"i18n.py"}:
            continue
        text = py_file.read_text(encoding="utf-8", errors="replace")
        keys.update(_T_CALL_RE.findall(text))
    return keys


def test_mod_code_uses_ui_keys():
    assert _used_keys(), "expected to discover t('...') calls in the mod"


def test_every_mod_ui_key_resolves_in_default_locale():
    engine = _mod_engine()
    missing = sorted(
        key for key in _used_keys() if engine.t(key).startswith("[missing:")
    )
    assert not missing, "mod UI keys missing from default locale: {}".format(missing)


def test_every_mod_ui_key_resolves_in_every_locale():
    engine = _mod_engine()
    failures = {}
    for locale in engine.locales():
        code = locale["code"]
        missing = sorted(
            key
            for key in _used_keys()
            if engine.t(key, lang=code).startswith("[missing:")
        )
        if missing:
            failures[code] = missing
    assert not failures, "mod UI keys missing per locale: {}".format(failures)


def _flatten(data, prefix=""):
    keys = []
    for key, value in data.items():
        full = prefix + "." + key if prefix else key
        if isinstance(value, dict):
            keys.extend(_flatten(value, full))
        else:
            keys.append(full)
    return keys


def test_mod_ui_locale_parity():
    import json

    en = json.loads((MOD_LOCALES / "ui" / "en-US.json").read_text(encoding="utf-8"))
    pt = json.loads((MOD_LOCALES / "ui" / "pt-BR.json").read_text(encoding="utf-8"))
    en_keys = set(_flatten(en))
    pt_keys = set(_flatten(pt))
    assert en_keys == pt_keys, "mod ui locale mismatch: missing={} extra={}".format(
        en_keys - pt_keys, pt_keys - en_keys
    )
