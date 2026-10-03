"""STBL/DBPF compilation for Sensewright sidecar (REQ-I18N-07).

Ported from mod/build_package.py to run in the FastAPI sidecar (stdlib only).
Produces byte-compatible .package files containing a single STBL resource.
"""

from __future__ import annotations

import struct
import zlib
from typing import Any, Dict, Union

# DBPF constants (TS4 / .package)
DBPF_MAGIC = b"DBPF"
DBPF_MAJOR_VERSION = 2
DBPF_MINOR_VERSION = 1
DBPF_HEADER_SIZE = 96
DBPF_INDEX_VERSION = 3
DBPF_INDEX_ENTRY_SIZE = 32
DBPF_COMPRESSION = 0x5A42
DBPF_COMPRESSION_UNKNOWN = 0x0001
DBPF_SIZE_COMPRESSED_FLAG = 0x80000000

# Resource type for a string table.
TYPE_STBL = 0x220557DA

# STBL resource key encoding: group 0 for the default locale (byte 0x00),
# 0x80000000 otherwise; instance = (locale_byte << 56) | base.
STBL_NON_DEFAULT_GROUP = 0x80000000

def plain_fnv1_64(text: str) -> int:
    """Plain FNV-1 64-bit hash (must match mod/build_package.py byte-for-byte)."""
    h = 0xCBF29CE484222325
    for byte in text.encode("utf-8"):
        h = (h * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
        h ^= byte
    return h


# Stable, mod-specific base for STBL instance keys (top byte reserved for locale).
# Computed (not hardcoded) so it always matches the Mod's build_package.py.
STBL_INSTANCE_BASE = plain_fnv1_64("sensewright.stbl") & 0x00FFFFFFFFFFFFFF


def fnv1_32(text: str) -> int:
    """FNV-1 32-bit hash (offset basis 0x811C9DC5, prime 0x01000193)."""
    hash_val = 0x811C9DC5
    for byte in text.encode("utf-8"):
        hash_val = (hash_val * 0x01000193) & 0xFFFFFFFF
        hash_val ^= byte
    return hash_val


def extract_stbl_strings(locale_data: Dict[str, Any]) -> Dict[str, str]:
    """Extract all strings from the 'stbl' namespace, flattening dotted keys."""
    strings: Dict[str, str] = {}

    def extract(obj: Any, prefix: str = "") -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                new_prefix = f"{prefix}.{k}" if prefix else k
                extract(v, new_prefix)
        elif isinstance(obj, str):
            strings[prefix] = obj
        elif isinstance(obj, list):
            # For lists, use the first item (deterministic rotation happens at runtime)
            if obj and isinstance(obj[0], str):
                strings[prefix] = obj[0]

    extract(locale_data.get("stbl", {}))
    return strings


def build_stbl_body(strings: Dict[str, str]) -> bytes:
    """Build the STBL v5 binary body from a {key: text} mapping.

    Entries are sorted by key hash for determinism.
    """
    items = sorted(
        ((fnv1_32(f"sensewright:{k}"), v) for k, v in strings.items()),
        key=lambda item: item[0],
    )

    entries = bytearray()
    for key_hash, text in items:
        value = text.encode("utf-8")
        entries.extend(struct.pack("<IBH", key_hash, 0, len(value)))
        entries.extend(value)

    header = bytearray()
    header.extend(b"STBL")
    header.extend(struct.pack("<H", 5))          # version
    header.extend(struct.pack("<B", 0))          # compressed
    header.extend(struct.pack("<I", len(items)))  # number of entries
    header.extend(struct.pack("<I", 0))          # locale (unused)
    header.extend(b"\x00\x00\x1a\x48\x00\x00")   # fixed trailer observed in TS4 STBL v5

    return bytes(header) + bytes(entries)


def stbl_resource_key(locale_byte: int) -> tuple[int, int]:
    """Compute the DBPF (group, instance) for an STBL of a given locale byte."""
    group = 0 if locale_byte == 0 else STBL_NON_DEFAULT_GROUP
    instance = ((locale_byte & 0xFF) << 56) | STBL_INSTANCE_BASE
    return group, instance


def compress_zlib(data: bytes) -> bytes:
    """Compress with zlib. TS4 stores a standard zlib stream (header+adler)."""
    return zlib.compress(data)


def build_dbpf(resources: list[tuple[int, int, int, bytes]]) -> bytes:
    """Serialise a list of (type, group, instance, raw_data) into a DBPF file.

    Every resource is stored zlib-compressed, matching the reference package.
    """
    resources = sorted(resources, key=lambda r: (r[0], r[1], r[2]))

    blob = bytearray()
    entries = []
    position = DBPF_HEADER_SIZE
    for res_type, res_group, res_instance, raw_data in resources:
        compressed = compress_zlib(raw_data)
        # TS4 stores the 64-bit instance as (high u32, low u32) in the index.
        # Verified against S4CL packages: the tuning's `s="0xHIGH LOW"` maps to
        # the first instance dword = high, second = low.
        entries.append((
            res_type,
            res_group,
            (res_instance >> 32) & 0xFFFFFFFF,
            res_instance & 0xFFFFFFFF,
            position,
            len(compressed) | DBPF_SIZE_COMPRESSED_FLAG,
            len(raw_data),
        ))
        blob.extend(compressed)
        position += len(compressed)

    index_offset = DBPF_HEADER_SIZE + len(blob)
    index_size = 4 + len(entries) * DBPF_INDEX_ENTRY_SIZE

    header = bytearray(DBPF_HEADER_SIZE)
    header[0:4] = DBPF_MAGIC
    struct.pack_into("<I", header, 0x04, DBPF_MAJOR_VERSION)
    struct.pack_into("<I", header, 0x08, DBPF_MINOR_VERSION)
    struct.pack_into("<I", header, 0x24, len(entries))
    struct.pack_into("<I", header, 0x2C, index_size)
    struct.pack_into("<I", header, 0x3C, DBPF_INDEX_VERSION)
    struct.pack_into("<I", header, 0x40, index_offset)

    index = bytearray()
    index.extend(struct.pack("<I", 0))  # 4-byte index prefix
    for entry in entries:
        index.extend(struct.pack(
            "<IIIIIIIHH",
            entry[0], entry[1], entry[2], entry[3],
            entry[4], entry[5], entry[6],
            DBPF_COMPRESSION, DBPF_COMPRESSION_UNKNOWN,
        ))

    return bytes(header) + bytes(blob) + bytes(index)


def strings_to_stbl(manifest_or_strings: Union[Dict[str, Any], Dict[str, str]]) -> Dict[str, str]:
    """Flatten a locale manifest (nested dict) or return a flat string map as {key: text}.

    If the input has an 'stbl' key, treat it as a locale manifest and extract
    STBL strings. Otherwise assume it's already a flat {key: text} mapping.
    """
    if "stbl" in manifest_or_strings:
        return extract_stbl_strings(manifest_or_strings)
    # Assume it's already a flat mapping; validate values are strings
    return {k: v for k, v in manifest_or_strings.items() if isinstance(v, str)}


def build_locale_package(locale_byte: int, strings: Dict[str, str]) -> bytes:
    """Return DBPF bytes for a single STBL resource built from {key: text}."""
    body = build_stbl_body(strings)
    group, instance = stbl_resource_key(locale_byte)
    return build_dbpf([(TYPE_STBL, group, instance, body)])


def write_locale_package(path: str, locale_byte: int, strings: Dict[str, str]) -> str:
    """Write build_locale_package(...) to path; return path."""
    data = build_locale_package(locale_byte, strings)
    with open(path, "wb") as f:
        f.write(data)
    return path