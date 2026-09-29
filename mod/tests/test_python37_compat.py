"""Structural guards for the in-game mod (Python 3.7 sandbox).

`from __future__ import annotations` stringifies annotations, which breaks TS4
command parsing (the game introspects annotation types at runtime for
``@sims4.commands.Command``). The skill forbids it anywhere in the mod, even in
modules without commands, because it is a landmine.
"""

from __future__ import annotations

import os

_PKG_DIR = os.path.join(os.path.dirname(__file__), "..", "simssense_mod")
_FORBIDDEN = "from __future__ import annotations"


def _mod_files():
    for name in sorted(os.listdir(_PKG_DIR)):
        if name.endswith(".py"):
            yield os.path.join(_PKG_DIR, name)


def test_no_future_annotations_import_in_mod():
    offenders = []
    for path in _mod_files():
        with open(path, encoding="utf-8") as handle:
            if any(_FORBIDDEN in line for line in handle):
                offenders.append(os.path.basename(path))

    assert offenders == [], "{} use '{}'".format(offenders, _FORBIDDEN)
