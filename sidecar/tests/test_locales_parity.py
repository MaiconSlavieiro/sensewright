"""Locale parity + placeholder validation (REQ-I18N-06).

Validates that every official locale registered in ``manifest.json`` has the
same key set as the default locale (source of truth), and that interpolation
variables in each translated string are a subset of the source string's
variables (preventing runtime KeyError from translator typos).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SIDECAR_LOCALES = REPO_ROOT / "sidecar" / "locales"

_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_.]*)\}")


def _load_json(path: Path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _flatten_keys(data, prefix=""):
    keys = []
    for key, value in data.items():
        full = prefix + "." + key if prefix else key
        if isinstance(value, dict):
            keys.extend(_flatten_keys(value, full))
        else:
            keys.append(full)
    return keys


def _placeholders(value):
    if isinstance(value, list):
        value = value[0] if value else ""
    if not isinstance(value, str):
        return set()
    # Exclude gender inflection macros and non-format braces.
    value = re.sub(r"\{g:[^}]*\}", "", value)
    return set(_PLACEHOLDER_RE.findall(value))


def _locale_codes():
    manifest = _load_json(SIDECAR_LOCALES / "manifest.json")
    return [loc["code"] for loc in manifest["locales"]]


def test_manifest_default_is_registered():
    manifest = _load_json(SIDECAR_LOCALES / "manifest.json")
    default = manifest["default_locale"]
    assert default in [loc["code"] for loc in manifest["locales"]]


def test_content_locales_parity():
    codes = _locale_codes()
    default = _load_json(SIDECAR_LOCALES / "manifest.json")["default_locale"]
    reference = _load_json(SIDECAR_LOCALES / "content" / "{}.json".format(default))
    ref_keys = set(_flatten_keys(reference))
    for code in codes:
        if code == default:
            continue
        data = _load_json(SIDECAR_LOCALES / "content" / "{}.json".format(code))
        keys = set(_flatten_keys(data))
        assert ref_keys == keys, "content/{}.json key mismatch: missing={} extra={}".format(
            code, ref_keys - keys, keys - ref_keys
        )


def test_ui_locales_parity():
    codes = _locale_codes()
    default = _load_json(SIDECAR_LOCALES / "manifest.json")["default_locale"]
    reference = _load_json(SIDECAR_LOCALES / "ui" / "{}.json".format(default))
    ref_keys = set(_flatten_keys(reference))
    for code in codes:
        if code == default:
            continue
        data = _load_json(SIDECAR_LOCALES / "ui" / "{}.json".format(code))
        keys = set(_flatten_keys(data))
        assert ref_keys == keys, "ui/{}.json key mismatch: missing={} extra={}".format(
            code, ref_keys - keys, keys - ref_keys
        )


def test_one_shot_examples_are_valid_json():
    """Few-shot examples must be valid JSON matching the parser contract.

    Non-JSON examples (e.g. ``[thought]...[/thought]``) make free models ignore
    the JSON-only instruction, so `_extract_json` fails and the deterministic
    fallback (thought-only, no intents) silently replaces every generation.
    """
    content_dir = SIDECAR_LOCALES / "content"
    required_keys = {
        "sim.chat": {"response", "thought", "intents", "trust_delta"},
        "sim.impulse": {"thought", "intents"},
        "sim.social": {"a_line", "b_line", "topic", "impact"},
    }
    for path in sorted(content_dir.glob("*.json")):
        data = _load_json(path)
        one_shot = (data.get("anchors") or {}).get("one_shot") or {}
        assert one_shot, "{}: no anchors.one_shot".format(path.name)
        for purpose, block in one_shot.items():
            parsed = json.loads(block)
            assert isinstance(parsed, dict), "{}:{} is not a JSON object".format(path.name, purpose)
            expected = required_keys.get(purpose)
            if expected:
                missing = expected - set(parsed)
                assert not missing, "{}:{} missing {}".format(path.name, purpose, missing)


def test_content_placeholder_subset():
    codes = _locale_codes()
    default = _load_json(SIDECAR_LOCALES / "manifest.json")["default_locale"]
    reference = _load_json(SIDECAR_LOCALES / "content" / "{}.json".format(default))
    ref_flat = dict(_iter_strings(reference))

    for code in codes:
        if code == default:
            continue
        data = _load_json(SIDECAR_LOCALES / "content" / "{}.json".format(code))
        for key, value in _iter_strings(data):
            if key not in ref_flat:
                continue
            source_vars = _placeholders(ref_flat[key])
            target_vars = _placeholders(value)
            assert target_vars <= source_vars, (
                "content/{}.json: '{}' introduces placeholders {} not present in source {}"
            ).format(code, key, target_vars - source_vars, source_vars)


def _iter_strings(data, prefix=""):
    for key, value in data.items():
        full = prefix + "." + key if prefix else key
        if isinstance(value, dict):
            yield from _iter_strings(value, full)
        else:
            yield full, value


def test_webui_locales_parity():
    webui = REPO_ROOT / "sidecar" / "sensewright_sidecar" / "webui" / "locales"
    files = sorted(webui.glob("*.json"))
    assert len(files) >= 2, "expected at least two SPA locale files"
    reference = _load_json(files[0])
    ref_keys = set(_flatten_keys(reference))
    for path in files[1:]:
        data = _load_json(path)
        keys = set(_flatten_keys(data))
        assert ref_keys == keys, "{} key mismatch: missing={} extra={}".format(
            path.name, ref_keys - keys, keys - ref_keys
        )
