"""Tests for i18n_compile module (REQ-I18N-07)."""

import os
import tempfile
import pytest

from sensewright_sidecar.i18n_compile import (
    STBL_INSTANCE_BASE,
    fnv1_32,
    extract_stbl_strings,
    build_stbl_body,
    stbl_resource_key,
    build_dbpf,
    build_locale_package,
    write_locale_package,
    strings_to_stbl,
)


class TestFNV1_32:
    """Known-value tests for FNV-1 32-bit hash (offset basis 0x811C9DC5, prime 0x01000193)."""

    def test_empty_string(self):
        assert fnv1_32("") == 0x811C9DC5

    def test_single_char(self):
        assert fnv1_32("a") == 0x050C5D7E

    def test_hello(self):
        assert fnv1_32("hello") == 0xB6FA7167

    def test_sensewright_prefix(self):
        assert fnv1_32("sensewright:test.key") == 0x2A9F5023
        assert fnv1_32("sensewright:ui.greeting") == 0x17F0917D


class TestExtractSTBLStrings:
    """Tests for extract_stbl_strings."""

    def test_flat_namespace(self):
        locale_data = {"stbl": {"greeting": "Hello", "farewell": "Goodbye"}}
        result = extract_stbl_strings(locale_data)
        assert result == {"greeting": "Hello", "farewell": "Goodbye"}

    def test_nested_namespace(self):
        locale_data = {
            "stbl": {
                "ui": {"greeting": "Hello", "farewell": "Goodbye"},
                "sim": {"mood": "Happy"},
            }
        }
        result = extract_stbl_strings(locale_data)
        assert result == {
            "ui.greeting": "Hello",
            "ui.farewell": "Goodbye",
            "sim.mood": "Happy",
        }

    def test_list_values_uses_first(self):
        locale_data = {"stbl": {"greeting": ["Hello", "Hi", "Hey"]}}
        result = extract_stbl_strings(locale_data)
        assert result == {"greeting": "Hello"}

    def test_missing_stbl_returns_empty(self):
        locale_data = {"ui": {"greeting": "Hello"}}
        result = extract_stbl_strings(locale_data)
        assert result == {}


class TestStringsToSTBL:
    """Tests for strings_to_stbl helper."""

    def test_manifest_with_stbl_key(self):
        manifest = {"stbl": {"ui": {"greeting": "Hello"}}}
        result = strings_to_stbl(manifest)
        assert result == {"ui.greeting": "Hello"}

    def test_flat_dict_passthrough(self):
        flat = {"key1": "value1", "key2": "value2"}
        result = strings_to_stbl(flat)
        assert result == flat

    def test_non_string_values_filtered(self):
        mixed = {"key1": "value1", "key2": 123, "key3": ["list"]}
        result = strings_to_stbl(mixed)
        assert result == {"key1": "value1"}


class TestBuildLocalePackage:
    """Tests for build_locale_package and write_locale_package."""

    @pytest.fixture
    def sample_strings(self):
        return {"ui.greeting": "Hello", "ui.farewell": "Goodbye", "sim.mood": "Happy"}

    def test_returns_bytes_with_dbpf_magic(self, sample_strings):
        data = build_locale_package(0x00, sample_strings)
        assert isinstance(data, bytes)
        assert data[:4] == b"DBPF"

    def test_idempotent_same_input_same_output(self, sample_strings):
        data1 = build_locale_package(0x00, sample_strings)
        data2 = build_locale_package(0x00, sample_strings)
        assert data1 == data2

    def test_different_locale_byte_produces_different_package(self, sample_strings):
        data_en = build_locale_package(0x00, sample_strings)
        data_fr = build_locale_package(0x01, sample_strings)
        assert data_en != data_fr

    def test_write_locale_package_writes_correct_bytes(self, sample_strings):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".package") as tmp:
            path = tmp.name
        try:
            returned = write_locale_package(path, 0x00, sample_strings)
            assert returned == path

            with open(path, "rb") as f:
                written = f.read()

            expected = build_locale_package(0x00, sample_strings)
            assert written == expected
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_empty_strings_produces_valid_package(self):
        data = build_locale_package(0x00, {})
        assert data[:4] == b"DBPF"
        # Should still have valid DBPF structure (header + index)
        assert len(data) >= 96  # DBPF header size


class TestSTBLResourceKey:
    """Tests for stbl_resource_key."""

    def test_default_locale_group_zero(self):
        group, instance = stbl_resource_key(0x00)
        assert group == 0
        assert (instance >> 56) & 0xFF == 0x00

    def test_non_default_locale_group_high_bit(self):
        group, instance = stbl_resource_key(0x01)
        assert group == 0x80000000
        assert (instance >> 56) & 0xFF == 0x01

    def test_instance_base_preserved(self):
        _, instance = stbl_resource_key(0x00)
        assert (instance & 0x00FFFFFFFFFFFFFF) == STBL_INSTANCE_BASE


class TestBuildDBPF:
    """Tests for build_dbpf internals."""

    def test_single_resource_structure(self):
        # Minimal STBL body
        body = b"STBL\x05\x00\x00\x00\x00\x00\x00\x1a\x48\x00\x00"
        resources = [(0x220557DA, 0, 0x00C8A7F3E2B1D4F5, body)]
        data = build_dbpf(resources)

        assert data[:4] == b"DBPF"
        # Header: index count at 0x24 should be 1
        import struct
        index_count = struct.unpack_from("<I", data, 0x24)[0]
        assert index_count == 1
        # Index version at 0x3C should be 3
        index_version = struct.unpack_from("<I", data, 0x3C)[0]
        assert index_version == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])