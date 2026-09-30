"""
Offline tests for the tuning package builder (``mod/build_package.py``).

No game required: the DBPF/STBL writer is pure Python. These lock in the resource
set (4 interaction tunings + one STBL per locale) and that **no** XmlInjector
snippet type is shipped anymore.

Run with the system Python (3.10+).
"""

import os
import sys

mod_dir = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, mod_dir)

import build_package  # noqa: E402

SNIPPET_TYPE = 0x7DF2169C


def test_interaction_resources_are_four():
    resources = build_package.interaction_resources()
    assert len(resources) == 4
    assert {r[1] for r in resources} == {build_package.INTERACTION_TUNING_TYPE}


def test_stbl_resources_cover_every_language():
    languages = build_package.load_stbl_languages()
    assert len(languages) >= 2
    assert all(language["strings"] for language in languages)


def test_package_ships_no_xmlinjector_snippet():
    assert SNIPPET_TYPE not in {r[1] for r in build_package.package_resources()}


def test_build_package_writes_a_dbpf(tmp_path):
    output = tmp_path / "Sensewright.package"
    result = build_package.build_package(output)
    assert result == output
    assert output.exists() and output.stat().st_size > 0
    assert output.read_bytes()[:4] == b"DBPF"
