#!/usr/bin/env python3
# Sensewright v2 — Build Script for .package (DBPF with Tuning XML + STBL)
# Python 3.10+ (build machine)
# Manifest-driven STBL compilation per REQ-I18N-07
#
# The DBPF container format and the STBL v5 binary format here were reverse
# engineered from a known-working Sims 4 package (S4CL) so the resulting file
# is byte-compatible with the game's resource loader:
#
#   DBPF:
#     - 96 byte header (major/minor, index count @0x24, index size @0x2C,
#       index version @0x3C, index offset @0x40)
#     - resource blobs start at 0x60
#     - index: 4 zero bytes then `count` 32-byte entries
#         (type, group, instance_hi, instance_lo, position, size, size2,
#          compression=0x5A42, unknown=0x0001), size = compressed_size|0x80000000
#
#   STBL v5 (after zlib decompression):
#     - 21 byte header: "STBL", u16 version(5), u8 compressed(0), u32 count,
#       u32 locale(0), 6 fixed bytes 00 00 1A 48 00 00
#     - entries: u32 key_hash, u8 flags(0), u16 length, length bytes (utf-8)

import os
import sys
import json
import re
import struct
import zlib
from pathlib import Path


MOD_DIR = Path(__file__).parent
TUNING_DIR = MOD_DIR / "tuning"
SIDECAR_LOCALES_DIR = MOD_DIR.parent / "sidecar" / "locales"
MOD_LOCALES_DIR = MOD_DIR / "sensewright_mod" / "locales"
DIST_DIR = MOD_DIR / "dist"
DIST_DIR.mkdir(exist_ok=True)

OUTPUT_PACKAGE = DIST_DIR / "Sensewright.package"
STBL_KEYS_OUTPUT = DIST_DIR / "stbl_keys.json"
TUNING_IDS_OUTPUT = DIST_DIR / "tuning_ids.json"

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

# Tuning resource types, keyed by the tuning `i="..."` attribute. Values come
# from the game's sims4/resources.pyc (Types registry).
TUNING_TYPES = {
    "buff": 0x6017E896,
    "trait": 0xCB5FDDC7,
    "snippet": 0x7DF2169C,
    "interaction": 0xE882D22F,
    "pie_menu_category": 0x03E9D964,
    "sim_data": 0x545AC67A,
}
DEFAULT_TUNING_TYPE = 0x545AC67A  # SimData fallback

# STBL resource key encoding: group 0 for the default locale (byte 0x00),
# 0x80000000 otherwise; instance = (locale_byte << 56) | base.
STBL_NON_DEFAULT_GROUP = 0x80000000


def read_file(path):
    with open(path, "rb") as f:
        return f.read()


def write_file(path, data):
    with open(path, "wb") as f:
        f.write(data)


def compress_zlib(data):
    """Compress with zlib. TS4 stores a standard zlib stream (header+adler)."""
    return zlib.compress(data)


def fnv1_32(text):
    """FNV-1 32-bit hash (offset basis 0x811C9DC5, prime 0x01000193)."""
    hash_val = 0x811C9DC5
    for byte in text.encode("utf-8"):
        hash_val = (hash_val * 0x01000193) & 0xFFFFFFFF
        hash_val ^= byte
    return hash_val


def plain_fnv1_64(text):
    """Plain FNV-1 64-bit hash (no high-bit convention)."""
    h = 0xCBF29CE484222325
    for byte in text.encode("utf-8"):
        h = (h * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
        h ^= byte
    return h


def fnv1_64(text):
    """FNV-1 64-bit hash with high bit set (TS4 tuning instance convention)."""
    return plain_fnv1_64(text.lower()) | 0x8000000000000000


# Stable, mod-specific base for STBL instance keys (top byte reserved for locale).
STBL_INSTANCE_BASE = plain_fnv1_64("sensewright.stbl") & 0x00FFFFFFFFFFFFFF


_TUNING_NAME_RE = re.compile(r'<I\b[^>]*\bn="([^"]+)"')
_TUNING_KIND_RE = re.compile(r'<I\b[^>]*\bi="([^"]+)"')
_TUNING_INSTANCE_RE = re.compile(r'\bs="[^"]*"')

# <V n="name" t="localized_string" p="STBL">stbl.some.key</V>
_LOCALIZED_STRING_RE = re.compile(
    r'<V\b([^>]*\bt\s*=\s*"localized_string"[^>]*\bp\s*=\s*"STBL"[^>]*)>'
    r'\s*stbl\.([A-Za-z0-9_.]+)\s*</V>'
)
_ATTR_N_RE = re.compile(r'\bn\s*=\s*"([^"]+)"')

# Symbolic tuning cross-reference: <T n="category">swtune:sw_pie_category</T>.
# Resolved to the referenced tuning's FNV-1 64-bit instance ID at build time so
# the XML never needs a hand-maintained numeric literal.
_TUNING_REF_RE = re.compile(r'swtune:([A-Za-z0-9_]+)')


def parse_tuning_name(xml_data):
    """Extract the tuning name (`n` attribute) from a tuning XML document."""
    if isinstance(xml_data, bytes):
        xml_data = xml_data.decode("utf-8", errors="replace")
    match = _TUNING_NAME_RE.search(xml_data)
    return match.group(1) if match else None


def parse_tuning_kind(xml_data):
    """Extract the tuning kind (`i` attribute) from a tuning XML document."""
    if isinstance(xml_data, bytes):
        xml_data = xml_data.decode("utf-8", errors="replace")
    match = _TUNING_KIND_RE.search(xml_data)
    return match.group(1) if match else None


def tuning_resource_type(kind):
    if kind is None:
        return DEFAULT_TUNING_TYPE
    return TUNING_TYPES.get(kind, DEFAULT_TUNING_TYPE)


def inject_tuning_instance(xml_data, instance):
    """Rewrite the tuning XML `s` attribute to the computed instance ID."""
    is_bytes = isinstance(xml_data, bytes)
    text = xml_data.decode("utf-8", errors="replace") if is_bytes else xml_data
    text = _TUNING_INSTANCE_RE.sub('s="{}"'.format(instance), text, count=1)
    return text.encode("utf-8") if is_bytes else text


def inject_localized_strings(xml_data, stbl_hashes):
    """Replace `stbl.<key>` localized-string references with their numeric hash.

    TS4 tuning expects localizable strings as a numeric STBL key inside a <T>
    element (e.g. <T n="name">0xDA253654</T>), not the dotted key path.
    """
    is_bytes = isinstance(xml_data, bytes)
    text = xml_data.decode("utf-8", errors="replace") if is_bytes else xml_data
    unreplaced = []

    def _replace(match):
        attrs = match.group(1)
        key = match.group(2)
        name_match = _ATTR_N_RE.search(attrs)
        if name_match is None:
            unreplaced.append(key)
            return match.group(0)
        key_hash = stbl_hashes.get(key)
        if key_hash is None:
            unreplaced.append(key)
            return match.group(0)
        return '<T n="{}">0x{:08X}</T>'.format(name_match.group(1), key_hash)

    text = _LOCALIZED_STRING_RE.sub(_replace, text)
    result = text.encode("utf-8") if is_bytes else text
    return result, unreplaced


def collect_tuning_instances():
    """Map every tuning `n` attribute to its FNV-1 64-bit instance ID."""
    instances = {}
    for xml_file in TUNING_DIR.rglob("*.xml"):
        name = parse_tuning_name(read_file(xml_file))
        if name:
            instances[name] = fnv1_64(name)
    return instances


def inject_tuning_refs(xml_data, name_to_instance):
    """Replace `swtune:<name>` tokens with the referenced numeric instance ID."""
    is_bytes = isinstance(xml_data, bytes)
    text = xml_data.decode("utf-8", errors="replace") if is_bytes else xml_data
    unresolved = []

    def _replace(match):
        name = match.group(1)
        instance = name_to_instance.get(name)
        if instance is None:
            unresolved.append(name)
            return match.group(0)
        return str(instance)

    text = _TUNING_REF_RE.sub(_replace, text)
    result = text.encode("utf-8") if is_bytes else text
    return result, unresolved


def load_manifest():
    """Load manifest from sidecar (primary) or mod (fallback)."""
    for manifest_path in [SIDECAR_LOCALES_DIR / "manifest.json", MOD_LOCALES_DIR / "manifest.json"]:
        if manifest_path.exists():
            with open(manifest_path, "r", encoding="utf-8") as f:
                return json.load(f)
    raise RuntimeError("manifest.json not found in sidecar or mod locales")


def load_ui_locale(code):
    """Load UI locale JSON from sidecar (primary) or mod (fallback)."""
    for base_dir in [SIDECAR_LOCALES_DIR, MOD_LOCALES_DIR]:
        locale_path = base_dir / "ui" / "{}.json".format(code)
        if locale_path.exists():
            with open(locale_path, "r", encoding="utf-8") as f:
                return json.load(f)
    raise RuntimeError("UI locale {} not found".format(code))


def extract_stbl_strings(locale_data):
    """Extract all strings from the 'stbl' namespace, flattening dotted keys."""
    strings = {}

    def extract(obj, prefix=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                new_prefix = "{}.{}".format(prefix, k) if prefix else k
                extract(v, new_prefix)
        elif isinstance(obj, str):
            strings[prefix] = obj
        elif isinstance(obj, list):
            # For lists, use the first item (deterministic rotation happens at runtime)
            if obj and isinstance(obj[0], str):
                strings[prefix] = obj[0]

    extract(locale_data.get("stbl", {}))
    return strings


def build_stbl_body(strings):
    """Build the STBL v5 binary body from a {key: text} mapping.

    Entries are sorted by key hash for determinism.
    """
    items = sorted(
        ((fnv1_32("sensewright:{}".format(k)), v) for k, v in strings.items()),
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


def stbl_resource_key(locale_byte):
    """Compute the DBPF (group, instance) for an STBL of a given locale byte."""
    group = 0 if locale_byte == 0 else STBL_NON_DEFAULT_GROUP
    instance = ((locale_byte & 0xFF) << 56) | STBL_INSTANCE_BASE
    return group, instance


def build_dbpf(resources):
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


def build_package():
    """Build the DBPF package with manifest-driven STBL compilation."""
    print("Building Sensewright.package...")

    manifest = load_manifest()
    locales = manifest.get("locales", [])
    default_locale = manifest.get("default_locale", "en-US")

    resources = []
    tuning_ids = {}
    stbl_keys_by_key = {}
    stbl_hashes = {}

    # ── STBL first (so we know the numeric hashes to inject into tuning XML) ──
    for loc in locales:
        code = loc.get("code")
        stbl_byte_str = loc.get("ts4_stbl_byte", "0x00")
        locale_byte = int(stbl_byte_str, 16)

        try:
            locale_data = load_ui_locale(code)
        except RuntimeError as e:
            print("  WARNING: {}".format(e))
            continue

        strings = extract_stbl_strings(locale_data)
        if not strings:
            print("  WARNING: No STBL strings found for {}".format(code))
            continue

        for key in strings:
            stbl_hashes.setdefault(key, fnv1_32("sensewright:{}".format(key)))
            stbl_keys_by_key.setdefault(key, {})[code] = "0x{:08X}".format(stbl_hashes[key])

        body = build_stbl_body(strings)
        group, instance = stbl_resource_key(locale_byte)
        resources.append((TYPE_STBL, group, instance, body))
        print("  Added STBL: {} (locale: 0x{:02X}, group: 0x{:08X}, instance: 0x{:016X}, {} strings)".format(
            code, locale_byte, group, instance, len(strings)))

    # Deterministic fallback hash map from the default locale if none were built.
    if not stbl_hashes:
        try:
            default_data = load_ui_locale(default_locale)
            for key in extract_stbl_strings(default_data):
                stbl_hashes[key] = fnv1_32("sensewright:{}".format(key))
        except RuntimeError:
            pass

    # ── Tuning XML ──────────────────────────────────────────────────────────
    name_to_instance = collect_tuning_instances()
    for xml_file in sorted(TUNING_DIR.rglob("*.xml")):
        rel_path = xml_file.relative_to(TUNING_DIR)
        data = read_file(xml_file)

        name = parse_tuning_name(data)
        kind = parse_tuning_kind(data)
        res_type = tuning_resource_type(kind)

        if name:
            instance = fnv1_64(name)
            data = inject_tuning_instance(data, instance)
            tuning_ids[name] = instance
            print("  Added XML: {} (kind: {}, type: 0x{:08X}, name: {}, instance: 0x{:016X})".format(
                rel_path, kind, res_type, name, instance))
        else:
            instance = fnv1_32(str(rel_path)) & 0xFFFFFFFFFFFFFFFF
            print("  WARNING: no n attribute in {}; using path hash instance".format(rel_path))

        data, unreplaced = inject_localized_strings(data, stbl_hashes)
        for key in unreplaced:
            print("  WARNING: unresolved STBL reference 'stbl.{}' in {}".format(key, rel_path))

        data, unresolved_refs = inject_tuning_refs(data, name_to_instance)
        for ref_name in unresolved_refs:
            print("  WARNING: unresolved tuning reference 'swtune:{}' in {}".format(ref_name, rel_path))

        resources.append((res_type, 0, instance, data))

    package_bytes = build_dbpf(resources)
    write_file(OUTPUT_PACKAGE, package_bytes)

    print("Created: {} ({} bytes, {} resources)".format(
        OUTPUT_PACKAGE, len(package_bytes), len(resources)))

    with open(STBL_KEYS_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(stbl_keys_by_key, f, indent=2, ensure_ascii=False)
    print("Emitted STBL key mapping: {}".format(STBL_KEYS_OUTPUT))

    tuning_ids_payload = {
        "version": 1,
        "algorithm": "fnv1_64_lower_highbit",
        "tunings": tuning_ids,
    }
    with open(TUNING_IDS_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(tuning_ids_payload, f, indent=2, ensure_ascii=False)
    print("Emitted tuning ID mapping: {} ({} tunings)".format(
        TUNING_IDS_OUTPUT, len(tuning_ids)))

    return True


def main():
    print("=" * 60)
    print("Sensewright v2 — Build .package (Manifest-driven STBL)")
    print("=" * 60)

    if not build_package():
        sys.exit(1)

    print("=" * 60)
    print("Build successful!")
    print("Output: {}".format(OUTPUT_PACKAGE))
    print("=" * 60)


if __name__ == "__main__":
    main()
