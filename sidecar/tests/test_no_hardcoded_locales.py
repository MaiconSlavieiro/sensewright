"""AST-based guard: no hardcoded locale literals in source (REQ-I18N-01).

Scans every Python module under ``mod/sensewright_mod/`` and
``sidecar/sensewright_sidecar/`` and fails if any string constant equals a
language code, STBL byte or client token. All language discovery must come from
``manifest.json``. Test files themselves are not scanned.
"""
from __future__ import annotations

import ast
from pathlib import Path

#: Exact string literals that are forbidden in source code.
FORBIDDEN_LITERALS = {
    "en", "pt-BR", "en-US", "pt", "0x00", "0x11",
    "eng_us", "en_us", "por_br", "pt_br", "en-us", "pt-br",
}

#: Repo root (this file is at <repo>/sidecar/tests/).
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

SOURCE_DIRS = [
    REPO_ROOT / "mod" / "sensewright_mod",
    REPO_ROOT / "sidecar" / "sensewright_sidecar",
]


def _find_offenders(path: Path):
    offenders = []
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return offenders
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return offenders
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value in FORBIDDEN_LITERALS:
                offenders.append((node.lineno, node.value))
    return offenders


def _python_files():
    for directory in SOURCE_DIRS:
        if not directory.is_dir():
            continue
        yield from sorted(directory.rglob("*.py"))


def test_no_hardcoded_locale_literals():
    violations = []
    for path in _python_files():
        for lineno, literal in _find_offenders(path):
            violations.append("{}:{} contains '{}'".format(path, lineno, literal))
    assert not violations, "hardcoded locale literals found:\n" + "\n".join(violations)
