"""Tests for the sw.probe autonomy snapshot helpers (F1)."""

from __future__ import annotations

import json

from sensewright_mod import probe


class _Fake:
    def __init__(self):
        self.value = 3
        self.name = "fake"

    def act(self):
        return self.value


def test_describe_lists_attrs_and_methods():
    desc = probe._describe(_Fake())

    assert desc["type"] == "_Fake"
    assert "value" in desc["attrs"]
    assert "act" in desc["methods"]


def test_describe_none_is_none():
    assert probe._describe(None) is None


def test_prune_drops_unknown_objects():
    payload = {"a": 1, "b": [1.5, object()], "c": {"d": True}}

    pruned = probe._prune(payload)

    assert pruned["a"] == 1
    assert pruned["c"]["d"] is True
    assert pruned["b"][0] == 1.5
    assert isinstance(pruned["b"][1], str)  # type name, not the object


def test_render_probe_is_header_plus_json():
    text = probe.render_probe({"sim": {"available": False}})

    assert text.startswith("=== ")
    body = text.split("\n", 1)[1]
    assert json.loads(body)["sim"]["available"] is False


def test_probe_modules_reports_importability():
    result = probe._probe_modules(
        {"area": ["json", "definitely_not_a_module_xyz"]}
    )

    assert result["area"]["json"]["importable"] is True
    assert "dumps" in result["area"]["json"]["names"]
    assert result["area"]["definitely_not_a_module_xyz"]["importable"] is False


def test_collect_probe_without_sim_is_available_false():
    data = probe.collect_probe(None, include_modules=False)

    assert data["sim"]["available"] is False


def test_dump_probe_writes_lines(monkeypatch):
    lines = []
    monkeypatch.setattr(probe, "debug_log", lambda message: lines.append(message))

    data = probe.dump_probe(None, include_modules=False)

    assert data["sim"]["available"] is False
    assert any("=== sw.probe ===" in line for line in lines)


def test_render_probe_sanitizes_leaked_objects():
    """L6: leaked objects are dropped, not masked as repr strings."""
    text = probe.render_probe({"leak": object(), "ok": 1})

    body = json.loads(text.split("\n", 1)[1])

    assert body["ok"] == 1
    assert "leak" not in body


def test_render_probe_drops_non_finite_floats():
    text = probe.render_probe({"x": float("inf"), "y": 1.5})

    body = json.loads(text.split("\n", 1)[1])

    assert body["x"] is None
    assert body["y"] == 1.5


def test_attr_logs_getattr_failures(monkeypatch):
    """H4: swallowed attribute errors are logged, not silent."""
    logged = []
    monkeypatch.setattr(
        probe, "log_exception", lambda where, exc: logged.append(where))

    class Boom(object):
        @property
        def bad(self):
            raise RuntimeError("nope")

    assert probe._attr(Boom(), ("bad",), "default") == "default"
    assert logged
