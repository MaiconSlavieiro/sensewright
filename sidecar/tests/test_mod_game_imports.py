"""Regression guard: the Mod must not import non-existent ``sims4.*`` submodules.

The game's packages live at the top level (``sims.sim``, ``services``,
``objects.*``, ``situations.*``); ``sims4`` only contains low-level modules
(``sims4.commands``, ``sims4.log``, ``sims4.math``, ``sims4.resources``, ...).
A typo such as ``from sims4.sim import Sim`` passes ``py_compile`` but raises
``ModuleNotFoundError`` inside the game and aborts the whole ``main`` import, so
the mod silently never loads. This test catches that class of bug offline.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MOD_DIR = REPO_ROOT / "mod" / "sensewright_mod"

#: Submodules that do NOT exist under ``sims4.`` (they are top-level packages).
_WRONG_SIMS4_SUBMODULES = {
    "sim", "sims", "services", "objects", "interactions", "situations",
    "relationships", "households", "careers", "traits", "statistics",
    "distributor", "buffs", "protocolbuffers", "server_commands", "venues",
    "whims", "aging", "pregnancy", "outfits", "occult", "skills",
}

_RE = re.compile(r"^\s*(?:from|import)\s+sims4\.([a-zA-Z0-9_]+)")


def test_no_nonexistent_sims4_submodule_imports():
    offenders = []
    for py_file in sorted(MOD_DIR.glob("*.py")):
        for lineno, line in enumerate(py_file.read_text(encoding="utf-8").splitlines(), 1):
            match = _RE.match(line)
            if match and match.group(1) in _WRONG_SIMS4_SUBMODULES:
                offenders.append("{}:{}: {}".format(py_file.name, lineno, line.strip()))
    assert not offenders, (
        "Mod imports a non-existent sims4 submodule (use the top-level package):\n"
        + "\n".join(offenders)
    )
