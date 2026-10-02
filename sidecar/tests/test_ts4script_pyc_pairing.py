"""Regression test for .ts4script bytecode/module pairing.

A previous build bug moved *every* ``.pyc`` in the shared ``__pycache__`` into
each output file, so e.g. ``chat_ui.pyc`` could contain ``pie_menu`` bytecode.
Every compiled module embeds its source filename, so we can verify pairing by
checking that ``<name>.pyc`` contains ``<name>.py``. Skipped when the artifact
has not been built.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TS4SCRIPT = REPO_ROOT / "mod" / "dist" / "Sensewright.ts4script"

pytestmark = pytest.mark.skipif(
    not TS4SCRIPT.is_file(), reason="Sensewright.ts4script not built"
)


def _entries():
    with zipfile.ZipFile(TS4SCRIPT) as archive:
        return {
            name: archive.read(name)
            for name in archive.namelist()
            if name.startswith("sensewright_mod/") and name.endswith(".pyc")
        }


def test_ts4script_has_modules():
    assert _entries(), "no module bytecode found in ts4script"


def test_each_pyc_embeds_its_own_source_name():
    mismatched = {}
    for name, data in _entries().items():
        module = Path(name).stem
        if module == "__init__":
            continue
        # co_filename is embedded as the full ".../chat_ui.py" path. Import
        # references use the dotted module name ("...chat_ui"), so ".py"
        # distinguishes the module's own bytecode from a wrong module's.
        if "{}.py".format(module).encode("utf-8") not in data:
            mismatched[name] = "missing own source filename '{}.py'".format(module)
    assert not mismatched, "corrupted .pyc pairing: {}".format(mismatched)
