# Sensewright v2 — Makefile
# Cross-platform build automation

.PHONY: all sidecar mod package test install doctor clean decompile help

# Default target
all: mod package

# Python commands
PY37 = py -3.7
PY310 = python

# Directories
MOD_DIR = mod
DIST_DIR = $(MOD_DIR)/dist
SIDECAR_DIR = sidecar
SCRIPTS_DIR = scripts

# Build targets
mod: $(DIST_DIR)/Sensewright.ts4script

package: $(DIST_DIR)/Sensewright.package

sidecar:
	@echo "Starting sidecar..."
	@cd $(SIDECAR_DIR) && $(PY310) main.py

# Build .ts4script (requires Python 3.7)
$(DIST_DIR)/Sensewright.ts4script: $(wildcard $(MOD_DIR)/sensewright_mod/*.py) $(wildcard $(MOD_DIR)/sensewright_mod/locales/*.json)
	@echo "Building .ts4script..."
	@$(PY310) $(MOD_DIR)/build.py

# Build .package (requires Python 3.10+)
$(DIST_DIR)/Sensewright.package: $(wildcard $(MOD_DIR)/tuning/**/*.xml) $(MOD_DIR)/tuning/stbl.json $(wildcard $(MOD_DIR)/sensewright_mod/locales/*.json)
	@echo "Building .package..."
	@$(PY310) $(MOD_DIR)/build_package.py

# Run syntax verification
test:
	@echo "Running Python 3.7 syntax check..."
	@for f in $(MOD_DIR)/sensewright_mod/*.py; do $(PY37) -m py_compile $$f; done
	@echo "Running Python 3.10 syntax check on build scripts..."
	@$(PY310) -m py_compile $(MOD_DIR)/build.py $(MOD_DIR)/build_package.py
	@echo "All syntax checks passed!"

# Install to TS4 Mods folder
install: mod package
	@echo "Installing mod..."
	@powershell -ExecutionPolicy Bypass -File $(SCRIPTS_DIR)/install-mod.ps1

# Run diagnostics
doctor:
	@powershell -ExecutionPolicy Bypass -File $(SCRIPTS_DIR)/doctor.ps1

# Clean build artifacts
clean:
	@echo "Cleaning..."
	@rm -rf $(DIST_DIR)
	@find $(MOD_DIR)/sensewright_mod -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
	@find $(MOD_DIR)/sensewright_mod -name '*.pyc' -delete 2>/dev/null || true
	@echo "Clean complete!"

# Decompile TS4 scripts
decompile:
	@powershell -ExecutionPolicy Bypass -File $(SCRIPTS_DIR)/decompile-scripts.ps1

# Development helper
dev:
	@powershell -ExecutionPolicy Bypass -File $(SCRIPTS_DIR)/dev.ps1

# Help
help:
	@echo "Sensewright v2 — Build System"
	@echo ""
	@echo "Targets:"
	@echo "  all       - Build both .ts4script and .package (default)"
	@echo "  mod       - Build .ts4script only"
	@echo "  package   - Build .package only"
	@echo "  sidecar   - Run sidecar development server"
	@echo "  test      - Run syntax verification"
	@echo "  install   - Install mod to TS4 Mods folder"
	@echo "  doctor    - Run diagnostics"
	@echo "  clean     - Clean build artifacts"
	@echo "  decompile - Decompile TS4 game scripts"
	@echo "  dev       - Development helper (build/test/clean/sidecar/install/doctor/decompile)"
	@echo "  help      - Show this help"
	@echo ""
	@echo "Requirements:"
	@echo "  Python 3.7 (for mod compilation) - 'py -3.7'"
	@echo "  Python 3.10+ (for build scripts) - 'python'"
	@echo "  S4CL and Lot 51 Core installed in TS4 Mods"