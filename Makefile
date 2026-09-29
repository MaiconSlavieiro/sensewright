# SimsSense Makefile
# Thin wrappers around scripts; use PowerShell scripts directly on Windows.

.PHONY: install run doctor status logs build-mod install-mod check

# Sidecar development
install:
	cd sidecar && uv sync --extra dev

run:
	cd sidecar && uv run python -m sims_sense_sidecar

doctor:
	powershell -ExecutionPolicy Bypass -File scripts/doctor.ps1

status:
	curl -s http://127.0.0.1:8765/v1/health | python -m json.tool

logs:
	Get-Content sidecar/data/sidecar.log -Wait -Tail 50

# Mod building (requires Python 3.7; see `make doctor`)
build-mod:
	python mod/build.py

# Dev-only build using the current interpreter (wrong bytecode for the game)
build-mod-dev:
	python mod/build.py --allow-any-python

install-mod:
	powershell -ExecutionPolicy Bypass -File scripts/install-mod.ps1

# Testing
check:
	cd sidecar && uv run pytest -q
	cd mod && python -m pytest tests -q

# Development helper
dev:
	powershell -ExecutionPolicy Bypass -File scripts/dev.ps1