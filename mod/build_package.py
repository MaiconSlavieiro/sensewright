"""
Build ``dist/Sensewright.package`` — the tuning package for the pie-menu spike.

Pure-Python DBPF writer (no S4S/FFDec). It stores the raw tuning XML resources
in ``mod/tuning/interactions/`` plus an English string table (STBL). The DBPF
layout and the STBL format are reimplemented from the TS4 package format; the
references studied were the MIT-licensed ShadySimDeals ``build_mod.py`` and the
Apache-2.0 TS4ControlAnySim interaction tuning.

Usage:  python mod/build_package.py
"""

import struct
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
DIST = REPO / "dist"
TARGET = DIST / "Sensewright.package"

INTERACTION_TUNING_TYPE = 0xE882D22F
SNIPPET_TYPE = 0x7DF2169C
STRING_TABLE_TYPE = 0x220557DA
STBL_GROUP = 0x00000000
# STBL instance's top byte encodes the language: 0x00 = ENG_US, 0x11 = POR_BR.
STBL_ENG_US = 0x00A1400000000001
STBL_POR_BR = 0x11A1400000000001

# Index-entry flags (7th field). Tuning resources are zlib-compressed, matching
# S4S-compiled packages; string tables are stored uncompressed.
FLAG_COMPRESSED = 0x00015A42
FLAG_UNCOMPRESSED = 0x00010000

# display-name key (from the interaction XML) -> localized string per language.
STRINGS_EN = {
    0xA1400001: "Open Panel",
    0xA1400002: "Chat\u2026",
    0xA1400003: "Confirm\u2026",
    0xA1400004: "HUD on/off",
}
STRINGS_PT = {
    0xA1400001: "Abrir Painel",
    0xA1400002: "Conversar\u2026",
    0xA1400003: "Confirmar\u2026",
    0xA1400004: "HUD on/off",
}


def build_stbl(entries):
    """Serialize a ``{key:int -> text:str}`` mapping into STBL bytes."""
    encoded = tuple(
        (int(key), str(value).encode("utf-8"))
        for key, value in sorted(entries.items())
    )
    data = bytearray(struct.pack(
        "<4sHBQ2sI", b"STBL", 5, 0, len(encoded), b"\0\0",
        sum(len(value) + 1 for _, value in encoded),
    ))
    for key, value in encoded:
        data += struct.pack("<IBH", key, 0, len(value))
        data += value
    return bytes(data)


def interaction_resources():
    """``(body, type, group, instance, uncompressed_size, flag)`` per XML.

    The game stores tuning as **zlib-compressed XML**, so the XML is compressed
    and the index carries the compressed size (``sf``) and the uncompressed size.
    """
    resources = []
    for path in sorted((ROOT / "tuning" / "interactions").glob("*.xml")):
        root = ET.parse(str(path)).getroot()
        instance = int(root.get("s"))
        xml_bytes = path.read_bytes()
        compressed = zlib.compress(xml_bytes, 9)
        resources.append((compressed, INTERACTION_TUNING_TYPE, 0, instance,
                          len(xml_bytes), FLAG_COMPRESSED))
    return resources


def snippet_resources():
    """XmlInjector snippet resources (``mod/tuning/snippets/*.xml``).

    The XmlInjector library reads these snippets at load and wires our
    interactions into the target's affordances (Sim / object pie menus).
    """
    resources = []
    for path in sorted((ROOT / "tuning" / "snippets").glob("*.xml")):
        root = ET.parse(str(path)).getroot()
        instance = int(root.get("s"))
        xml_bytes = path.read_bytes()
        compressed = zlib.compress(xml_bytes, 9)
        resources.append((compressed, SNIPPET_TYPE, 0, instance,
                          len(xml_bytes), FLAG_COMPRESSED))
    return resources


def stbl_resources():
    """Localized string tables: one per supported language (en + pt-BR)."""
    resources = []
    for instance, strings in ((STBL_ENG_US, STRINGS_EN), (STBL_POR_BR, STRINGS_PT)):
        body = build_stbl(strings)
        resources.append((body, STRING_TABLE_TYPE, STBL_GROUP, instance,
                          len(body), FLAG_UNCOMPRESSED))
    return resources


def package_resources():
    resources = interaction_resources()
    resources += snippet_resources()
    resources += stbl_resources()
    return resources


def build_package(target=TARGET):
    resources = package_resources()
    resource_offset = 96
    index = bytearray()
    payload = bytearray()
    for body, resource_type, group, instance, uncompressed, flag in resources:
        index += struct.pack(
            "<IIIIIIII",
            resource_type, group, instance >> 32, instance & 0xFFFFFFFF,
            resource_offset + len(payload), len(body) | 0x80000000,
            uncompressed, flag,
        )
        payload += body
    index_offset = resource_offset + len(payload)
    header = bytearray(96)
    struct.pack_into("<4sII", header, 0, b"DBPF", 2, 1)
    # Match S4S-built packages: 0x28 holds 0 (the 32-bit index offset field is
    # unused); the real index offset lives at 0x40 as a 64-bit value.
    struct.pack_into("<III", header, 36, len(resources), 0, 4 + len(index))
    struct.pack_into("<IQ", header, 60, 3, index_offset)
    target.write_bytes(header + payload + struct.pack("<I", 0) + index)
    return target


if __name__ == "__main__":
    DIST.mkdir(exist_ok=True)
    package = build_package()
    print("built {} ({} resources)".format(package, len(package_resources())))
