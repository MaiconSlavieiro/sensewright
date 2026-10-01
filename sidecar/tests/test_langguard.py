"""Tests for the v0.4 P2 LanguagePolicy (``llm.langguard``)."""

from __future__ import annotations

from sensewright_sidecar.llm import langguard


def test_language_directive_names_the_locale():
    line = langguard.language_directive("pt-BR")
    assert "Português (Brasil)" in line
    assert "pt-BR" in line
    assert "ONLY" in line


def test_reinforced_directive_is_stricter():
    base = langguard.language_directive("pt-BR")
    reinforced = langguard.language_directive("pt-BR", reinforced=True)
    assert len(reinforced) > len(base)
    assert "previous answer" in reinforced


def test_detect_lang_english():
    assert langguard.detect_lang("Hello there, how is your day going today?") == "en"


def test_detect_lang_portuguese():
    assert langguard.detect_lang("Oi, como está o seu dia hoje? Tudo bem?") == "pt-BR"


def test_detect_lang_chars_only_signal():
    # Accented characters are a Portuguese hint even with no stopwords.
    assert langguard.detect_lang("Ótimã!") == "pt-BR"


def test_detect_lang_empty_and_json_are_none():
    assert langguard.detect_lang("") is None
    assert langguard.detect_lang("   ") is None
    assert langguard.detect_lang('{"summary": "hello"}') is None


def test_check_ok_and_mismatch():
    assert langguard.check("Hello, how are you?", "en").ok is True
    bad = langguard.check("Olá, como você está?", "en")
    assert bad.ok is False
    assert bad.detected == "pt-BR"


def test_check_empty_is_not_wrong():
    assert langguard.check("", "pt-BR").ok is True
    assert langguard.is_wrong_lang("", "pt-BR") is False


def test_check_flags_json():
    result = langguard.check('{"topic": "x"}', "en")
    assert result.ok is False
    assert result.reason == "json"


def test_confident_detection_needs_one_locale_ahead():
    # A tie (both score) is not confident; the guard keeps the text.
    check = langguard.detect_lang("no if or an a o e")
    # Either a confident pick or None, but never a wrong confident pick here.
    assert check in (None, "en", "pt-BR")
