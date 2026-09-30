"""Tests for the data-driven content-locale loader (``content_i18n``)."""

from __future__ import annotations

import json
import os

from sensewright_sidecar import content_i18n


def _locale_dir() -> str:
    return os.path.join(os.path.dirname(content_i18n.__file__), "locales_content")


def _load_locale(code: str) -> dict:
    with open(os.path.join(_locale_dir(), f"{code}.json"), encoding="utf-8") as handle:
        return json.load(handle)


# ─── manifest discovery ──────────────────────────────────────────────────


def test_default_lang_comes_from_manifest():
    assert content_i18n.default_lang() == "en"


def test_available_locales_come_from_manifest():
    assert content_i18n.available_locales() == ["en", "pt-BR"]


def test_locale_entries_expose_code_name_and_match():
    entries = {entry["code"]: entry for entry in content_i18n.locale_entries()}
    assert entries["en"]["name"] == "English"
    assert "en" in entries["en"]["match"]
    assert entries["pt-BR"]["name"] == "Português (Brasil)"
    assert "pt" in entries["pt-BR"]["match"]
    assert "brazilian" in entries["pt-BR"]["match"]


def test_every_locale_has_a_json_file():
    for code in content_i18n.available_locales():
        assert os.path.isfile(os.path.join(_locale_dir(), f"{code}.json")), code


# ─── language_name ───────────────────────────────────────────────────────


def test_language_name_known_variants():
    assert content_i18n.language_name("en") == "English"
    assert content_i18n.language_name("pt-BR") == "Português (Brasil)"
    assert content_i18n.language_name("pt_br") == "Português (Brasil)"


def test_language_name_unknown_returns_tag():
    assert content_i18n.language_name("fr") == "fr"
    assert content_i18n.language_name("auto") == "auto"


# ─── normalize_lang ──────────────────────────────────────────────────────


def test_normalize_lang_known_variants():
    assert content_i18n.normalize_lang("en") == "en"
    assert content_i18n.normalize_lang("EN") == "en"
    assert content_i18n.normalize_lang("en-US") == "en"
    assert content_i18n.normalize_lang("pt-BR") == "pt-BR"
    assert content_i18n.normalize_lang("pt_br") == "pt-BR"
    assert content_i18n.normalize_lang("ptbr") == "pt-BR"
    assert content_i18n.normalize_lang("pt") == "pt-BR"
    assert content_i18n.normalize_lang("portuguese") == "pt-BR"


def test_normalize_lang_enum_repr_strings():
    assert content_i18n.normalize_lang("Locale.PORTUGUESE_BRAZIL") == "pt-BR"
    assert content_i18n.normalize_lang("Language.BrazilianPortuguese") == "pt-BR"
    assert content_i18n.normalize_lang("Language.English") == "en"
    assert content_i18n.normalize_lang("Locale.ENGLISH_UNITED_STATES") == "en"


def test_normalize_lang_unknown_falls_back_to_default():
    assert content_i18n.normalize_lang("fr") == "en"
    assert content_i18n.normalize_lang("es") == "en"
    assert content_i18n.normalize_lang("") == "en"
    assert content_i18n.normalize_lang(None) == "en"


# ─── t() ─────────────────────────────────────────────────────────────────


def test_t_translates_and_formats():
    assert content_i18n.t("en", "sys.health.ok") == "OK"
    assert content_i18n.t("pt-BR", "consolidation.felt", label="joy") == "senti joy"


def test_t_unknown_lang_falls_back_to_default_locale():
    assert content_i18n.t("fr", "profile.head", name="Ana") == "Ana is a Sim"


def test_t_unknown_key_returns_key():
    assert content_i18n.t("en", "does.not.exist") == "does.not.exist"


def test_t_format_error_returns_raw_template():
    # A missing format argument must never raise.
    assert content_i18n.t("en", "profile.head") == "{name} is a Sim"


def test_meta_markers_are_per_locale():
    assert "the user" in content_i18n.t("en", "sys.meta_markers")
    assert "o usuário" in content_i18n.t("pt-BR", "sys.meta_markers")


# ─── parity ──────────────────────────────────────────────────────────────


def test_locale_files_have_parity_with_default():
    default = content_i18n.default_lang()
    default_keys = set(_load_locale(default))
    problems: list[str] = []
    for code in content_i18n.available_locales():
        keys = set(_load_locale(code))
        missing = default_keys - keys
        extra = keys - default_keys
        if missing:
            problems.append(f"{code} missing keys: {sorted(missing)}")
        if extra:
            problems.append(f"{code} extra keys: {sorted(extra)}")
    assert not problems, "\n".join(problems)
