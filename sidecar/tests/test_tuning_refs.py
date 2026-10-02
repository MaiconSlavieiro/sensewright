"""Regression test for tuning XML cross-references and module bindings.

The package builder resolves symbolic ``swtune:<name>`` references to numeric
instance IDs at build time. A typo silently leaves the literal token in the XML,
which makes the game fail to load the tuning. This test catches that offline.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TUNING_DIR = REPO_ROOT / "mod" / "tuning"

_NAME_RE = re.compile(r'<I\b[^>]*\bn="([^"]+)"')
_REF_RE = re.compile(r"swtune:([A-Za-z0-9_]+)")


def _xml_files():
    return sorted(TUNING_DIR.rglob("*.xml"))


def test_tuning_files_exist():
    assert _xml_files(), "expected tuning XML files"


def test_every_tuning_has_a_name():
    unnamed = [str(p.relative_to(TUNING_DIR)) for p in _xml_files() if not _NAME_RE.search(p.read_text(encoding="utf-8"))]
    assert not unnamed, "tuning XML without an n attribute: {}".format(unnamed)


def test_every_tuning_reference_resolves():
    names = set()
    for path in _xml_files():
        names.update(_NAME_RE.findall(path.read_text(encoding="utf-8")))

    unresolved = {}
    for path in _xml_files():
        refs = set(_REF_RE.findall(path.read_text(encoding="utf-8")))
        missing = sorted(ref for ref in refs if ref not in names)
        if missing:
            unresolved[str(path.relative_to(TUNING_DIR))] = missing
    assert not unresolved, "unresolved swtune references: {}".format(unresolved)


def test_interactions_use_real_binding_modules():
    """Interaction/pie-category tunings must bind to real Python modules."""
    expected_modules = {
        "buff": ("buffs.buff",),
        "trait": ("traits.traits",),
        "interaction": (
            "sensewright_mod.interactions",
            "sensewright_mod.object_interactions",
        ),
        "pie_menu_category": ("interactions.pie_menu_category",),
        "object": ("objects.game_object",),
        "situation": ("sensewright_mod.visit_situation",),
    }
    for path in _xml_files():
        text = path.read_text(encoding="utf-8")
        kind_match = re.search(r'<I\b[^>]*\bi="([^"]+)"', text)
        module_match = re.search(r'<I\b[^>]*\bm="([^"]+)"', text)
        if not kind_match or not module_match:
            continue
        kind = kind_match.group(1)
        module = module_match.group(1)
        if kind in expected_modules:
            assert module in expected_modules[kind], "{}: {} tuning binds to {}".format(
                path.name, kind, module
            )
