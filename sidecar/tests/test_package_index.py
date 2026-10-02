"""Regression test for the DBPF index instance encoding.

TS4 stores a resource's 64-bit instance in the index as (high u32, low u32).
Getting that order wrong makes the game load every tuning under an instance
that does not match the tuning's ``s`` attribute, so the instance manager never
finds them (interactions/buffs/traits silently absent). Verified against
S4CL's shipped example package.
"""
from __future__ import annotations

import re
import struct
import zlib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PACKAGE = REPO_ROOT / "mod" / "dist" / "Sensewright.package"

TYPE_STBL = 0x220557DA
TUNING_TYPES = {0x6017E896, 0xCB5FDDC7, 0x7DF2169C, 0xE882D22F, 0x03E9D964, 0x545AC67A}

_S_RE = re.compile(r'<I\b[^>]*\bs="(\d+)"')

pytestmark = pytest.mark.skipif(not PACKAGE.is_file(), reason="package not built")


def _entries():
    data = PACKAGE.read_bytes()
    count = struct.unpack_from("<I", data, 0x24)[0]
    index_offset = struct.unpack_from("<I", data, 0x40)[0]
    pos = index_offset + 4
    for _ in range(count):
        res_type, group, high, low, offset, size, size2, comp, unk = struct.unpack_from(
            "<IIIIIIIHH", data, pos
        )
        pos += 32
        blob = data[offset : offset + (size & 0x7FFFFFFF)]
        try:
            raw = zlib.decompress(blob)
        except zlib.error:
            raw = blob
        yield res_type, group, (high << 32) | low, raw


def test_index_instance_matches_tuning_s():
    mismatches = []
    checked = 0
    for res_type, _group, instance, raw in _entries():
        if res_type not in TUNING_TYPES:
            continue
        text = raw.decode("utf-8", errors="replace")
        match = _S_RE.search(text)
        if not match:
            continue
        checked += 1
        s_value = int(match.group(1))
        if instance != s_value:
            mismatches.append(
                "type=0x{:08X} index=0x{:016X} s=0x{:016X}".format(res_type, instance, s_value)
            )
    assert checked, "expected tuning resources in the package"
    assert not mismatches, "DBPF index instance != tuning s (hi/lo swapped?): {}".format(mismatches)


def test_stbl_instance_locale_byte_in_high_byte():
    stbls = [(g, i) for t, g, i, _ in _entries() if t == TYPE_STBL]
    assert stbls, "expected STBL resources"
    # Default locale (0x00) uses group 0; others use 0x80000000 with the locale
    # byte in the top byte of the instance.
    for group, instance in stbls:
        if group == 0:
            assert (instance >> 56) == 0x00
        else:
            assert (instance >> 56) != 0x00
