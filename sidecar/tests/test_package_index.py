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
TUNING_TYPES = {
    0x6017E896, 0xCB5FDDC7, 0x7DF2169C, 0xE882D22F, 0x03E9D964, 0x545AC67A,
    0xB61DE6B4, 0xFBC3AEEB,
}

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


# --- Custom menu icons -------------------------------------------------------
# A regression once shipped icons that the UI silently ignored: the DDS header
# was 124 bytes instead of 128 (missing dwReserved2), so pixel data started at
# 0x7C instead of 0x80 and every DXT5 block was shifted 4 bytes. Each interaction
# also had no `pie_menu_icon`, and each pie-menu category had no SimData (the
# client binary the UI actually reads). These tests pin all three.

TYPE_DDS = 0x00B2D882
TYPE_INTERACTION = 0xE882D22F
TYPE_PIE_MENU_CATEGORY = 0x03E9D964
TYPE_SIMDATA = 0x545AC67A
SIMDATA_GROUP_PIE_MENU_CATEGORY = 0x00E9D967

_ICON_REF_RE = re.compile(r'<T n="key"[^>]*>2f7d0004:00000000:([0-9A-Fa-f]{16})</T>')


def _dxt5_payload_size(w, h):
    """Total DXT5 byte size of a full mip chain (each level >= one 4x4 block)."""
    total = 0
    while True:
        total += max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * 16
        if w == 1 and h == 1:
            break
        w, h = max(1, w // 2), max(1, h // 2)
    return total


def test_custom_icon_dds_headers_are_wellformed():
    icons = [(i, r) for t, _g, i, r in _entries() if t == TYPE_DDS]
    assert icons, "expected custom icon DDS resources"
    for instance, raw in icons:
        assert raw[:4] == b"DDS ", "icon 0x{:016X} is not a DDS".format(instance)
        assert struct.unpack_from("<I", raw, 4)[0] == 124, "DDS header size must be 124"
        flags = struct.unpack_from("<I", raw, 8)[0]
        h, w = struct.unpack_from("<II", raw, 12)
        depth = struct.unpack_from("<I", raw, 24)[0]
        fourcc = raw[84:88]
        assert fourcc == b"DXT5", "icon 0x{:016X} is not DXT5".format(instance)
        assert flags & 0x00080000, "icon 0x{:016X} missing DDSD_LINEARSIZE".format(instance)
        assert depth == 0, "icon 0x{:016X} depth must be 0 for a 2D texture".format(instance)
        # The whole file must be the 128-byte header + the exact DXT5 mip chain,
        # which fails loudly if the header is ever shortened to 124 bytes again.
        assert len(raw) == 128 + _dxt5_payload_size(w, h), (
            "icon 0x{:016X} size {} != 128 + {}".format(instance, len(raw), _dxt5_payload_size(w, h))
        )


def test_interaction_pie_menu_icons_resolve_to_packaged_dds():
    dds_instances = {i for t, _g, i, _r in _entries() if t == TYPE_DDS}
    referenced = set()
    for res_type, _group, _instance, raw in _entries():
        if res_type != TYPE_INTERACTION:
            continue
        text = raw.decode("utf-8", errors="replace")
        referenced.update(int(m, 16) for m in _ICON_REF_RE.findall(text))
    assert referenced, "expected interactions carrying a pie_menu_icon"
    missing = sorted("0x{:016X}".format(i) for i in referenced - dds_instances)
    assert not missing, "interaction icons reference missing DDS resources: {}".format(missing)


def test_pie_menu_categories_ship_client_simdata():
    categories = {i for t, _g, i, _r in _entries() if t == TYPE_PIE_MENU_CATEGORY}
    assert categories, "expected pie menu categories"
    simdata = {
        i
        for t, g, i, _r in _entries()
        if t == TYPE_SIMDATA and g == SIMDATA_GROUP_PIE_MENU_CATEGORY
    }
    missing = sorted("0x{:016X}".format(i) for i in categories - simdata)
    assert not missing, (
        "pie menu categories without SimData (UI would fail to open): {}".format(missing)
    )
