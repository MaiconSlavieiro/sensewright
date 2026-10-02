#!/usr/bin/env python3
# Sensewright v2 — Build Script for .package (DBPF with Tuning XML + STBL)
# Python 3.10+ (build machine)
# Manifest-driven STBL compilation per REQ-I18N-07

import os
import sys
import json
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

# DBPF constants
DBPF_MAGIC = b"DBPF"
DBPF_VERSION = 0x00000002
DBPF_INDEX_VERSION = 0x0000000C

# Resource types
TYPE_XML = 0x0333406C  # XML tuning
TYPE_STBL = 0x220557DA  # String table


def read_file(path):
    with open(path, "rb") as f:
        return f.read()


def write_file(path, data):
    with open(path, "wb") as f:
        f.write(data)


def compress_zlib(data):
    """Compress with zlib (DBPF uses zlib with no header)."""
    return zlib.compress(data)[2:-4]  # Remove zlib header and Adler32


def fnv1_32(text):
    """FNV-1 32-bit hash (offset basis 0x811C9DC5, prime 0x01000193)."""
    hash_val = 0x811C9DC5
    for byte in text.encode("utf-8"):
        hash_val = (hash_val * 0x01000193) & 0xFFFFFFFF
        hash_val ^= byte
    return hash_val


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
    """Extract all strings from the 'stbl' namespace, flattening with dotted keys."""
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


def build_stbl_resource(strings, locale_byte):
    """Build STBL binary resource from flattened string dict."""
    # STBL format:
    # Header: 4 bytes magic (STBL), 4 bytes version, 4 bytes num_strings, 4 bytes locale
    # Index: for each string: 4 bytes key_hash, 4 bytes offset, 4 bytes length
    # Strings: UTF-8 null-terminated

    sorted_keys = sorted(strings.keys())

    string_data = bytearray()
    index_entries = []

    for key in sorted_keys:
        value = strings[key]
        # FNV-1 hash of "sensewright:" + key
        hash_key = "sensewright:{}".format(key)
        key_hash = fnv1_32(hash_key)
        offset = len(string_data)
        utf8_value = value.encode("utf-8")
        string_data.extend(utf8_value)
        string_data.append(0)  # Null terminator
        length = len(utf8_value)
        index_entries.append((key_hash, offset, length))

    header = struct.pack("<4sIII", b"STBL", 1, len(sorted_keys), locale_byte)

    index = bytearray()
    for key_hash, offset, length in index_entries:
        index.extend(struct.pack("<III", key_hash, offset, length))

    return header + index + string_data, sorted_keys


def build_package():
    """Build the DBPF package with manifest-driven STBL compilation."""
    print("Building Sensewright.package...")

    # Load manifest
    manifest = load_manifest()
    locales = manifest.get("locales", [])
    default_locale = manifest.get("default_locale", "en-US")

    # Collect all resources
    resources = []  # (type, group, instance, data)

    # Add XML tuning files
    for xml_file in TUNING_DIR.rglob("*.xml"):
        rel_path = xml_file.relative_to(TUNING_DIR)
        instance = fnv1_32(str(rel_path)) & 0xFFFFFFFFFFFFFFFF
        group = TYPE_XML
        data = read_file(xml_file)
        compressed = compress_zlib(data)
        resources.append((TYPE_XML, group, instance, compressed))
        print("  Added XML: {} (instance: 0x{:016X})".format(rel_path, instance))

    # Add STBL resources per locale in manifest
    all_stbl_keys = {}

    for loc in locales:
        code = loc.get("code")
        stbl_byte_str = loc.get("ts4_stbl_byte", "0x00")
        locale_byte = int(stbl_byte_str, 16)

        print("  Processing locale: {} (STBL byte: 0x{:02X})".format(code, locale_byte))

        try:
            locale_data = load_ui_locale(code)
        except RuntimeError as e:
            print("  WARNING: {}".format(e))
            continue

        strings = extract_stbl_strings(locale_data)
        if not strings:
            print("  WARNING: No STBL strings found for {}".format(code))
            continue

        stbl_data, keys = build_stbl_resource(strings, locale_byte)
        compressed = compress_zlib(stbl_data)

        # Instance ID for STBL: locale byte in upper 32 bits
        instance = (locale_byte << 32) & 0xFFFFFFFFFFFFFFFF
        resources.append((TYPE_STBL, TYPE_STBL, instance, compressed))
        print("  Added STBL: {} (locale: 0x{:02X}, instance: 0x{:016X}, {} strings)".format(
            code, locale_byte, instance, len(keys)))

        # Record key -> hash mapping for this locale
        for key in keys:
            hash_key = "sensewright:{}".format(key)
            key_hash = fnv1_32(hash_key)
            if key not in all_stbl_keys:
                all_stbl_keys[key] = {}
            all_stbl_keys[key][code] = "0x{:08X}".format(key_hash)

    # Build DBPF
    resources.sort(key=lambda r: (r[0], r[1], r[2]))

    index_entries = []
    file_data = bytearray()
    file_offset = 0

    for res_type, res_group, res_instance, res_data in resources:
        index_entries.append({
            "type": res_type,
            "group": res_group,
            "instance": res_instance,
            "offset": file_offset,
            "size": len(res_data),
            "compressed_size": len(res_data),
            "compression": 1  # zlib
        })
        file_data.extend(res_data)
        file_offset += len(res_data)

    with open(OUTPUT_PACKAGE, "wb") as f:
        # Header
        f.write(DBPF_MAGIC)
        f.write(struct.pack("<I", DBPF_VERSION))
        f.write(struct.pack("<I", 0))  # Index offset (will fill later)
        f.write(struct.pack("<I", len(resources)))  # Index count
        f.write(struct.pack("<I", 0))  # Index size (will fill later)
        f.write(struct.pack("<I", DBPF_INDEX_VERSION))
        f.write(struct.pack("<I", 0))  # Hole offset
        f.write(struct.pack("<I", 0))  # Hole size
        f.write(struct.pack("<I", 0))  # User data 1
        f.write(struct.pack("<I", 0))  # User data 2

        header_size = f.tell()

        # Write file data
        f.write(file_data)

        # Write index
        index_offset = f.tell()
        for entry in index_entries:
            f.write(struct.pack("<IIIQIIB",
                entry["type"],
                entry["group"],
                entry["instance"] & 0xFFFFFFFF,
                entry["instance"] >> 32,
                entry["offset"],
                entry["size"],
                entry["compression"]
            ))

        index_size = f.tell() - index_offset

        # Update header with index info
        f.seek(4)
        f.write(struct.pack("<I", index_offset))
        f.write(struct.pack("<I", len(resources)))
        f.write(struct.pack("<I", index_size))

    print("Created: {} ({} bytes, {} resources)".format(
        OUTPUT_PACKAGE, OUTPUT_PACKAGE.stat().st_size, len(resources)))

    # Emit stbl_keys.json
    with open(STBL_KEYS_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(all_stbl_keys, f, indent=2, ensure_ascii=False)
    print("Emitted STBL key mapping: {}".format(STBL_KEYS_OUTPUT))

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