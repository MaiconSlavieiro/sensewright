#!/usr/bin/env python3
"""
Build script for Sensewright .ts4script package.
Compiles Python 3.7 bytecode and creates the zip archive.
Must be run with Python 3.7 (or --allow-any-python).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import List, Optional


def find_python37(python_arg: Optional[str] = None) -> Optional[List[str]]:
    """
    Locate a Python 3.7 interpreter.

    Priority: --python arg -> PY37 env -> py -3.7 -> python3.7 -> python3 -> python.
    Returns the interpreter command as a list (e.g. ``["py", "-3.7"]`` or a path
    to the executable), or None if no Python 3.7 is found.
    """
    candidates: List[List[str]] = []

    if python_arg:
        candidates.append([python_arg])

    env_py = os.environ.get("PY37")
    if env_py:
        candidates.append([env_py])

    # Windows launcher
    if sys.platform == "win32":
        candidates.append(["py", "-3.7"])

    # Unix-style
    candidates.extend([["python3.7"], ["python3"], ["python"]])

    for candidate in candidates:
        try:
            result = subprocess.run(
                candidate + ["-c", "import sys; print(sys.version_info[:2])"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0 and "(3, 7)" in result.stdout.strip():
                return candidate
        except Exception:
            continue

    return None


def compile_package(package_dir: Path, python_cmd: List[str], verbose: bool = False) -> bool:
    """
    Compile all .py files in the package to .pyc using the target Python interpreter.
    Uses compileall for batch compilation. ``python_cmd`` is a command list.
    """
    try:
        # Remove stale bytecode from any previous interpreter before rebuilding.
        clean_build(package_dir)

        # Use compileall via the target interpreter.
        # Note: Python 3.7's compileall has no -v flag, so verbose simply omits -q.
        cmd = list(python_cmd) + [
            "-m", "compileall",
            "-b",  # legacy layout: write .pyc next to .py
            "-f",  # force rebuild
        ]
        if not verbose:
            cmd.append("-q")
        cmd.append(str(package_dir))

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            print("Compilation failed:")
            print(result.stderr)
            return False

        if verbose:
            print(result.stdout)

        return True
    except subprocess.TimeoutExpired:
        print("Compilation timed out")
        return False
    except Exception as e:
        print("Compilation error: {}".format(e))
        return False


def create_ts4script(package_dir: Path, output_path: Path, verbose: bool = False) -> bool:
    """
    Create the .ts4script zip file containing the package with .pyc files.
    The archive structure should be:
    sensewright_mod/
    sensewright_mod/__init__.pyc
    sensewright_mod/*.pyc
    sensewright_mod/locales/*.json
    """
    try:
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            # Walk the package directory
            for root, dirs, files in os.walk(package_dir):
                # Skip __pycache__ directories (we want .pyc files at package level)
                if "__pycache__" in root:
                    continue

                for file in files:
                    file_path = Path(root) / file
                    # Compute archive path relative to package parent
                    rel_path = file_path.relative_to(package_dir.parent)
                    arcname = str(rel_path).replace(os.sep, "/")

                    if verbose:
                        print("  Adding: {}".format(arcname))

                    zf.write(file_path, arcname)

        return True
    except Exception as e:
        print("Failed to create .ts4script: {}".format(e))
        return False


def list_archive_contents(archive_path: Path) -> List[str]:
    """List contents of the .ts4script archive."""
    try:
        with zipfile.ZipFile(archive_path, "r") as zf:
            return sorted(zf.namelist())
    except Exception:
        return []


def clean_build(package_dir: Path) -> None:
    """Remove __pycache__ directories and .pyc files."""
    for root, dirs, files in os.walk(package_dir, topdown=False):
        for file in files:
            if file.endswith(".pyc"):
                try:
                    os.remove(os.path.join(root, file))
                except Exception:
                    pass
        for dir_name in dirs:
            if dir_name == "__pycache__":
                try:
                    shutil.rmtree(os.path.join(root, dir_name))
                except Exception:
                    pass


def main():
    parser = argparse.ArgumentParser(description="Build Sensewright .ts4script package")
    parser.add_argument("--out", default="dist/Sensewright.ts4script", help="Output path for .ts4script")
    parser.add_argument("--python", help="Path to Python 3.7 interpreter")
    parser.add_argument("--allow-any-python", action="store_true", help="Allow any Python version (not recommended)")
    parser.add_argument("--clean", action="store_true", help="Clean build artifacts before building")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    args = parser.parse_args()

    # Paths
    repo_root = Path(__file__).parent.parent
    mod_dir = repo_root / "mod"
    package_dir = mod_dir / "sensewright_mod"
    output_path = Path(args.out)

    if not package_dir.exists():
        print("ERROR: Package directory not found: {}".format(package_dir))
        return 1

    # Clean if requested
    if args.clean:
        print("Cleaning build artifacts...")
        clean_build(package_dir)
        if output_path.exists():
            output_path.unlink()
        print("Clean complete.")

    # Find Python 3.7
    python_cmd = find_python37(args.python)

    if python_cmd is None:
        print("ERROR: Python 3.7 not found.")
        print("  Tried: --python, $PY37, py -3.7, python3.7, python3, python")
        if args.allow_any_python:
            print("  --allow-any-python specified, using current interpreter: {}".format(sys.executable))
            python_cmd = [sys.executable]
        else:
            print("  Use --allow-any-python to proceed with current Python ({}).".format(sys.version.split()[0]))
            return 1
    else:
        print("Using Python 3.7: {}".format(" ".join(python_cmd)))

    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Compile
    print("Compiling package with Python 3.7...")
    if not compile_package(package_dir, python_cmd, args.verbose):
        return 1

    # Create .ts4script
    print("Creating .ts4script: {}".format(output_path))
    if not create_ts4script(package_dir, output_path, args.verbose):
        return 1

    # List contents
    contents = list_archive_contents(output_path)
    print("\nArchive contents ({} files):".format(len(contents)))
    for item in contents:
        print("  {}".format(item))

    print("\nBuild successful: {}".format(output_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())