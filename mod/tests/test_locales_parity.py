"""
Tests for locale parity across every locale declared in ``locales/manifest.json``.

Data-driven: adding a language to the manifest automatically brings it under
test here (no per-language hardcoding). Run with system Python (3.10+).
"""

import os
import re
import sys
import json

# Add mod directory to path
mod_dir = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, mod_dir)

import pytest


LOCALES_DIR = os.path.join(mod_dir, "sensewright_mod", "locales")


def load_manifest() -> dict:
    with open(os.path.join(LOCALES_DIR, "manifest.json"), "r", encoding="utf-8") as f:
        return json.load(f)


def load_locale(locale: str) -> dict:
    path = os.path.join(LOCALES_DIR, "{}.json".format(locale))
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def manifest_codes() -> list:
    return [e["code"] for e in load_manifest().get("locales", []) if e.get("code")]


def test_manifest_and_locale_files_exist():
    manifest = load_manifest()
    codes = manifest_codes()
    assert codes, "manifest has no locales"
    assert manifest.get("default") in codes, "manifest default not declared"
    for code in codes:
        path = os.path.join(LOCALES_DIR, "{}.json".format(code))
        assert os.path.exists(path), "{}.json not found".format(code)


def test_meta_matches_manifest():
    for entry in load_manifest().get("locales", []):
        data = load_locale(entry["code"])
        assert data["_meta"]["locale"] == entry["code"]
        assert data["_meta"]["name"] == entry["name"]
        assert "version" in data["_meta"]


def test_key_parity_against_default():
    default = load_manifest()["default"]
    base = set(load_locale(default).keys()) - {"_meta"}
    for code in manifest_codes():
        keys = set(load_locale(code).keys()) - {"_meta"}
        missing = base - keys
        extra = keys - base
        assert not missing, "{} missing keys: {}".format(code, sorted(missing))
        assert not extra, "{} extra keys: {}".format(code, sorted(extra))


def test_required_keys_present():
    required = {
        "cmd.help.title",
        "cmd.help.body",
        "cmd.status.title",
        "cmd.status.body",
        "cmd.status.sidecar_down",
        "cmd.reset.done",
        "cmd.forget.done",
        "cmd.autonomy.set",
        "cmd.lang.set",
        "cmd.lang.invalid",
        "cmd.god.opening",
        "cmd.god.unavailable",
        "notify.sidecar_starting",
        "notify.sidecar_ready",
        "notify.sidecar_unreachable",
        "notify.no_llm_native",
        "error.brain_foggy",
        "error.rate_limited",
        "error.bad_request",
        "error.internal",
    }
    default = load_manifest()["default"]
    missing = required - set(load_locale(default).keys())
    assert not missing, "Required keys missing in {}: {}".format(default, sorted(missing))


def test_no_empty_values():
    for code in manifest_codes():
        for key, value in load_locale(code).items():
            if key == "_meta":
                continue
            assert value != "", "Empty value in {} for key: {}".format(code, key)


def test_placeholders_consistency():
    default = load_manifest()["default"]
    base = load_locale(default)
    pattern = re.compile(r"\{(\w+)\}")
    for code in manifest_codes():
        if code == default:
            continue
        data = load_locale(code)
        for key, value in base.items():
            if key == "_meta":
                continue
            en_ph = set(pattern.findall(value))
            other_ph = set(pattern.findall(data.get(key, "")))
            assert en_ph == other_ph, (
                "Placeholder mismatch for {} ({} vs {}): {} != {}".format(
                    key, default, code, en_ph, other_ph
                )
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
