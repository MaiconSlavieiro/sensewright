#!/usr/bin/env python3
# Sensewright v2 — Build Script for .ts4script
# Python 3.10+ (build machine), produces Python 3.7 bytecode

import os
import sys
import zipfile
import shutil
import subprocess
import tempfile
from pathlib import Path


MOD_DIR = Path(__file__).parent
SRC_DIR = MOD_DIR / "sensewright_mod"
DIST_DIR = MOD_DIR / "dist"
DIST_DIR.mkdir(exist_ok=True)

OUTPUT_SCRIPT = DIST_DIR / "Sensewright.ts4script"

# Python 3.7 magic number: 42 0d 0d 0a (0x0a0d0d42 little-endian)
PY37_MAGIC = b"\x42\x0d\x0d\x0a"


def verify_python37():
    """Verify we're using Python 3.7 for compilation."""
    if sys.platform == "win32":
        try:
            result = subprocess.run(["py", "-3.7", "--version"], capture_output=True, text=True)
            if result.returncode == 0 and "3.7" in result.stdout:
                print("Found Python 3.7: {}".format(result.stdout.strip()))
                return ["py", "-3.7"]
        except Exception:
            pass
    else:
        try:
            result = subprocess.run(["python3.7", "--version"], capture_output=True, text=True)
            if result.returncode == 0 and "3.7" in result.stdout:
                print("Found Python 3.7: {}".format(result.stdout.strip()))
                return ["python3.7"]
        except Exception:
            pass

    print("ERROR: Python 3.7 not found. Please install Python 3.7.9")
    print("The .ts4script must be compiled with Python 3.7 bytecode (magic 42 0d 0d 0a)")
    sys.exit(1)


def compile_python37(python_cmd, source_dir, output_dir):
    """Compile Python source to .pyc using Python 3.7."""
    cmd_str = " ".join(python_cmd)
    print("Compiling with {}...".format(cmd_str))

    base_cmd = python_cmd + ["-m", "py_compile"]
    for py_file in source_dir.rglob("*.py"):
        rel_path = py_file.relative_to(source_dir)
        out_file = output_dir / rel_path.with_suffix(".pyc")
        out_file.parent.mkdir(parents=True, exist_ok=True)

        result = subprocess.run(base_cmd + [str(py_file)], capture_output=True, text=True)
        if result.returncode != 0:
            print("ERROR compiling {}:".format(py_file))
            print(result.stderr)
            return False

        # Move compiled file to output dir
        pycache_dir = py_file.parent / "__pycache__"
        for compiled in pycache_dir.glob("*.pyc"):
            shutil.move(str(compiled), str(out_file))

    # Clean up __pycache__ directories
    for pycache in source_dir.rglob("__pycache__"):
        shutil.rmtree(pycache, ignore_errors=True)

    return True


def verify_bytecode_magic(pyc_dir):
    """Verify all .pyc files have Python 3.7 magic number."""
    print("Verifying bytecode magic numbers...")
    for pyc_file in pyc_dir.rglob("*.pyc"):
        with open(pyc_file, "rb") as f:
            magic = f.read(4)
            if magic != PY37_MAGIC:
                print("ERROR: {} has wrong magic number: {}".format(pyc_file, magic.hex()))
                print("Expected: {}".format(PY37_MAGIC.hex()))
                return False
    print("All .pyc files have correct Python 3.7 magic number")
    return True


def create_ts4script(compiled_dir, output_path):
    """Create the .ts4script zip file."""
    print("Creating .ts4script: {}".format(output_path))

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for pyc_file in compiled_dir.rglob("*.pyc"):
            arcname = pyc_file.relative_to(compiled_dir)
            zf.write(pyc_file, arcname)

        # Include locale JSON files (manifest + ui/*.json)
        locales_dir = MOD_DIR / "sensewright_mod" / "locales"
        for locale_file in locales_dir.rglob("*.json"):
            arcname = "locales/{}".format(locale_file.relative_to(locales_dir))
            zf.write(locale_file, arcname)

    print("Created: {} ({} bytes)".format(output_path, output_path.stat().st_size))
    return True


def main():
    print("=" * 60)
    print("Sensewright v2 — Build .ts4script")
    print("=" * 60)

    python_cmd = verify_python37()

    with tempfile.TemporaryDirectory() as tmpdir:
        compiled_dir = Path(tmpdir) / "compiled"
        compiled_dir.mkdir()

        if not compile_python37(python_cmd, SRC_DIR, compiled_dir):
            sys.exit(1)

        if not verify_bytecode_magic(compiled_dir):
            sys.exit(1)

        if not create_ts4script(compiled_dir, OUTPUT_SCRIPT):
            sys.exit(1)

    print("=" * 60)
    print("Build successful!")
    print("Output: {}".format(OUTPUT_SCRIPT))
    print("=" * 60)


if __name__ == "__main__":
    main()