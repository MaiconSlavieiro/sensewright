"""
Tests for sidecar discovery / launch resolution in config.py (offline).
Run with system Python (3.10+).
"""

import os
import sys

mod_dir = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, mod_dir)

from sensewright_mod import config  # noqa: E402


def test_sidecar_launch_prefers_packaged_exe(monkeypatch):
    exe = r"C:\mods\Sensewright\sidecar\Sensewright-sidecar.exe"
    monkeypatch.setattr(config, "sidecar_exe", lambda: exe)
    monkeypatch.setattr(config, "_safe_exists", lambda path: path == exe)
    monkeypatch.setattr(config, "sidecar_dir", lambda: r"C:\mods\Sensewright\sidecar")

    command, cwd = config.sidecar_launch()

    assert command == [exe]
    assert cwd == r"C:\mods\Sensewright\sidecar"


def test_sidecar_launch_falls_back_to_source(monkeypatch):
    monkeypatch.setattr(config, "sidecar_exe", lambda: r"C:\x\Sensewright-sidecar.exe")
    monkeypatch.setattr(config, "_safe_exists", lambda path: False)
    monkeypatch.setattr(config, "_safe_isdir", lambda path: True)
    monkeypatch.setattr(config, "sidecar_dir", lambda: r"C:\x\sidecar")
    monkeypatch.setattr(config, "find_python", lambda: r"C:\py\python.exe")

    command, cwd = config.sidecar_launch()

    assert command == [r"C:\py\python.exe", "-m", "sensewright_sidecar"]
    assert cwd == r"C:\x\sidecar"


def test_sidecar_launch_empty_without_python(monkeypatch):
    monkeypatch.setattr(config, "sidecar_exe", lambda: "")
    monkeypatch.setattr(config, "_safe_exists", lambda path: False)
    monkeypatch.setattr(config, "sidecar_dir", lambda: r"C:\x\sidecar")
    monkeypatch.setattr(config, "find_python", lambda: "")

    assert config.sidecar_launch() == ([], "")


def test_find_python_env_override_wins(monkeypatch, tmp_path):
    interpreter = tmp_path / "python.exe"
    interpreter.write_text("", encoding="utf-8")
    monkeypatch.setenv("SENSEWRIGHT_PYTHON", str(interpreter))

    assert config.find_python() == str(interpreter)


def test_find_python_prefers_sidecar_venv(monkeypatch, tmp_path):
    monkeypatch.delenv("SENSEWRIGHT_PYTHON", raising=False)
    sidecar = tmp_path / "sidecar"
    venv_python = sidecar / ".venv" / "Scripts" / "python.exe"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("", encoding="utf-8")
    monkeypatch.setattr(config, "sidecar_dir", lambda: str(sidecar))

    assert config.find_python() == str(venv_python)


def test_read_interpreter_hint_reads_installer_file(monkeypatch, tmp_path):
    interpreter = tmp_path / "python.exe"
    interpreter.write_text("", encoding="utf-8")
    sidecar = tmp_path / "sidecar"
    sidecar.mkdir()
    (sidecar / "python.txt").write_text(str(interpreter) + "\n", encoding="utf-8")
    monkeypatch.setattr(config, "sidecar_dir", lambda: str(sidecar))

    assert config.read_interpreter_hint() == str(interpreter)


def test_read_interpreter_hint_strips_utf8_bom(monkeypatch, tmp_path):
    interpreter = tmp_path / "python.exe"
    interpreter.write_text("", encoding="utf-8")
    sidecar = tmp_path / "sidecar"
    sidecar.mkdir()
    (sidecar / "python.txt").write_bytes(
        b"\xef\xbb\xbf" + str(interpreter).encode("utf-8"))
    monkeypatch.setattr(config, "sidecar_dir", lambda: str(sidecar))

    assert config.read_interpreter_hint() == str(interpreter)


def test_read_interpreter_hint_ignores_stale_path(monkeypatch, tmp_path):
    sidecar = tmp_path / "sidecar"
    sidecar.mkdir()
    (sidecar / "python.txt").write_text(str(tmp_path / "gone.exe"), encoding="utf-8")
    monkeypatch.setattr(config, "sidecar_dir", lambda: str(sidecar))

    assert config.read_interpreter_hint() == ""


def test_find_python_uses_interpreter_hint_without_venv(monkeypatch, tmp_path):
    monkeypatch.delenv("SENSEWRIGHT_PYTHON", raising=False)
    interpreter = tmp_path / "python.exe"
    interpreter.write_text("", encoding="utf-8")
    sidecar = tmp_path / "sidecar"
    sidecar.mkdir()
    (sidecar / "python.txt").write_text(str(interpreter), encoding="utf-8")
    monkeypatch.setattr(config, "sidecar_dir", lambda: str(sidecar))

    assert config.find_python() == str(interpreter)


def test_write_autonomy_level_creates_agents_section(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "mod_root", lambda: str(tmp_path))

    assert config.write_autonomy_level("semi") is True

    content = (tmp_path / "sensewright.toml").read_text(encoding="utf-8")
    assert "[agents]" in content
    assert 'autonomy = "semi"' in content


def test_write_autonomy_level_updates_existing_preserving_other_keys(monkeypatch, tmp_path):
    toml_path = tmp_path / "sensewright.toml"
    toml_path.write_text(
        '[ui]\nlanguage = "pt-BR"\n\n[agents]\nautonomy = "off"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "mod_root", lambda: str(tmp_path))

    assert config.write_autonomy_level("full") is True

    content = toml_path.read_text(encoding="utf-8")
    assert 'language = "pt-BR"' in content
    assert 'autonomy = "full"' in content
    assert 'autonomy = "off"' not in content


def test_write_autonomy_level_does_not_clobber_autonomy_default(monkeypatch, tmp_path):
    toml_path = tmp_path / "sensewright.toml"
    toml_path.write_text(
        '[agents]\nautonomy_default = "semi"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "mod_root", lambda: str(tmp_path))

    assert config.write_autonomy_level("full") is True

    content = toml_path.read_text(encoding="utf-8")
    assert 'autonomy_default = "semi"' in content
    assert 'autonomy = "full"' in content


def test_write_autonomy_level_false_without_root(monkeypatch):
    monkeypatch.setattr(config, "mod_root", lambda: "")

    assert config.write_autonomy_level("semi") is False


def test_read_autonomy_level_round_trip(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "mod_root", lambda: str(tmp_path))
    assert config.read_autonomy_level() == ""

    config.write_autonomy_level("full")

    assert config.read_autonomy_level() == "full"


def test_read_autonomy_level_empty_without_root(monkeypatch):
    monkeypatch.setattr(config, "mod_root", lambda: "")

    assert config.read_autonomy_level() == ""


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
