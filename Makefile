.DEFAULT_GOAL := help
.PHONY: help run run-compile startup-time clean install install-py install-cli install-system-deps install-desktop test tests lint dist build-launcher release

UNAME_S := $(shell uname -s)
PYTHON  = .venv/bin/python3
COMPILE = @$(PYTHON) -m compileall -q src 2>/dev/null || true
RUN_ENV = $(DYLD_ENV) PYTHON_JIT=1 PYTHONPATH=..:$$PYTHONPATH
IDE_CMD = $(CURDIR)/$(PYTHON) zen_ide_window.py
APP_NAME    := Zen IDE
APP_BUNDLE  := dist/$(APP_NAME).app
APP_ID      := com.zen-ide.app
APP_VERSION := $(shell grep '^version' pyproject.toml | head -1 | sed 's/.*"\(.*\)"/\1/')
PROJECT_DIR := $(CURDIR)

# macOS: Homebrew libs need DYLD_FALLBACK_LIBRARY_PATH for GLib typelib lookups.
# SIP strips DYLD_* from /bin/sh children, so we pass it inline on each recipe.
ifeq ($(UNAME_S),Darwin)
  BREW_PREFIX := $(shell brew --prefix 2>/dev/null)
  ifneq ($(BREW_PREFIX),)
    DYLD_ENV = DYLD_FALLBACK_LIBRARY_PATH=$(BREW_PREFIX)/lib
  endif
endif

help: ## Show this help
	@echo "Zen IDE - Available targets:"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ── Development ──────────────────────────────────────────────────────

run: ## Run Zen IDE
	cd src && unset MAKELEVEL MAKEFLAGS && $(RUN_ENV) $(IDE_CMD)

run-compile: ## Run Zen IDE (with bytecode pre-compilation)
	$(COMPILE)
	cd src && unset MAKELEVEL MAKEFLAGS && $(RUN_ENV) $(IDE_CMD)

startup-time: ## Measure startup time (opens and closes IDE)
	@echo "Measuring Zen IDE startup time..."
	$(COMPILE)
	@cd src && $(RUN_ENV) ZEN_STARTUP_BENCH=1 $(IDE_CMD)

lint: ## Run ruff linter and formatter (auto-fix)
	uvx ruff check --fix && uvx ruff format

lint-check: ## Run ruff linter and formatter (check only, no changes)
	uvx ruff check && uvx ruff format --check

test: ## Run tests with pytest
	uv run --no-sync python -m pytest tests/ --color=yes

tests: test ## Alias for test

# ── Installation ─────────────────────────────────────────────────────

install: install-system-deps install-py install-cli ## Install everything (system deps + venv + dev + build + CLI)

install-py: ## Create venv and install all dependencies (including dev and build extras)
	@test -d .venv || uv venv
	uv sync --extra dev --extra build

install-system-deps: ## Install system dependencies (GTK4 stack via brew/apt)
ifeq ($(UNAME_S),Darwin)
	@echo "Installing GTK4 system dependencies via Homebrew..."
	brew install gtk4 gtksourceview5 vte3 libadwaita gobject-introspection pkg-config ripgrep 2>/dev/null || true
else ifeq ($(UNAME_S),Linux)
	@echo "Installing GTK4 system dependencies via apt..."
	sudo apt-get update
	sudo apt-get install -y libgirepository1.0-dev libgirepository-2.0-dev libcairo2-dev python3-gi python3-gi-cairo \
		gir1.2-gtk-4.0 gir1.2-gtksource-5 gir1.2-adw-1 gir1.2-vte-3.91 ripgrep
endif


install-cli: ## Install 'zen' command to open Zen IDE from terminal
	@mkdir -p ~/.local/bin
	@ln -sf $(CURDIR)/zen ~/.local/bin/zen
	@echo "✓ Installed 'zen' command → $(CURDIR)/zen"
	@echo "  Usage: zen .          (open current directory)"
	@echo "         zen file.py    (open a file)"
	@case "$$PATH" in *$$HOME/.local/bin*) ;; *) echo "  ⚠  Add ~/.local/bin to your PATH:"; echo "     export PATH=\"\$$HOME/.local/bin:\$$PATH\"" ;; esac

# ── Build & Distribution ─────────────────────────────────────────────

LAUNCHER_SRC := tools/launcher/launcher.swift
LAUNCHER_BIN := tools/launcher/zen-launcher

build-launcher: ## Compile the native macOS launcher as a universal binary (arm64 + x86_64)
ifeq ($(UNAME_S),Darwin)
	@echo "Compiling universal zen-launcher (arm64 + x86_64)..."
	@swiftc -O -target arm64-apple-macos13.0  $(LAUNCHER_SRC) -o $(LAUNCHER_BIN)-arm64
	@swiftc -O -target x86_64-apple-macos13.0 $(LAUNCHER_SRC) -o $(LAUNCHER_BIN)-x86_64
	@lipo -create $(LAUNCHER_BIN)-arm64 $(LAUNCHER_BIN)-x86_64 -output $(LAUNCHER_BIN)
	@rm -f $(LAUNCHER_BIN)-arm64 $(LAUNCHER_BIN)-x86_64
	@echo "✓ Built universal launcher: $$(file $(LAUNCHER_BIN) | sed 's/.*: //')"
endif

dist: build-launcher ## Build standalone app (macOS .app bundle, Linux AppImage)
ifeq ($(UNAME_S),Darwin)
	@echo "Building standalone $(APP_NAME).app with PyInstaller..."
	@rm -rf build dist
	uv run pyinstaller "Zen IDE.spec" --noconfirm
	@echo "Stripping debug symbols from binaries..."
	@find "$(APP_BUNDLE)/Contents/Frameworks" -type f \( -name '*.dylib' -o -name '*.so' \) \
		-exec strip -x {} 2>/dev/null \;
	@find "$(APP_BUNDLE)/Contents/Resources" -type f -name '*.so' \
		-exec strip -x {} 2>/dev/null \;
	@strip -x "$(APP_BUNDLE)/Contents/Frameworks/Python.framework/Versions/3.14/Python" 2>/dev/null || true
	@echo "Trimming ICU data (locale reduction)..."
	@$(PYTHON) tools/trim_icu_data.py "$(APP_BUNDLE)"
	@echo "Signing app bundle..."
	@find "$(APP_BUNDLE)" -name '*.dylib' -o -name '*.so' -o -name 'Python' | \
		xargs -I{} codesign --force --sign - {} 2>/dev/null || true
	@codesign --force --deep --sign - --entitlements entitlements.plist "$(APP_BUNDLE)"
	@echo "Installing to /Applications..."
	@rm -rf "/Applications/$(APP_NAME).app"
	@cp -R "$(APP_BUNDLE)" /Applications/
	@echo "✓ $(APP_NAME) installed to /Applications/$(APP_NAME).app"
	@echo "  Size: $$(du -sh '/Applications/$(APP_NAME).app' | cut -f1)"
else ifeq ($(UNAME_S),Linux)
	@bash tools/build_appimage.sh
else
	@echo "Unsupported platform: $(UNAME_S)"
	@exit 1
endif

install-desktop: ## Install .desktop file and icon for current user (Linux)
ifeq ($(UNAME_S),Linux)
	@echo "Installing .desktop file and icon..."
	@mkdir -p ~/.local/share/applications ~/.local/share/icons/hicolor/256x256/apps
	@cp zen_icon.png ~/.local/share/icons/hicolor/256x256/apps/zen-ide.png
	@sed 's|^Icon=.*|Icon=$(CURDIR)/zen_icon.png|;s|^Exec=.*|Exec=$(CURDIR)/zen %F|' zen-ide.desktop > ~/.local/share/applications/zen-ide.desktop
	@gtk-update-icon-cache ~/.local/share/icons/hicolor/ 2>/dev/null || true
	@update-desktop-database ~/.local/share/applications/ 2>/dev/null || true
	@echo "✓ Installed zen-ide.desktop and icon for current user"
else
	@echo "install-desktop is only supported on Linux"
endif

clean: ## Remove build artifacts and caches
	rm -rf __pycache__ .python_ide "Zen IDE.app" build dist dist_native *.egg-info zen_ide.build zen_ide.dist zen_ide.onefile-build
	find . -path ./.venv -prune -o -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache

release: ## Generate release notes (AI or manual), confirm, then trigger full CI release
	@VERSION=$(APP_VERSION); TAG="v$$VERSION"; \
	echo "Releasing Zen IDE $$VERSION..."; \
	if git ls-remote --tags origin "refs/tags/$$TAG" 2>/dev/null | grep -q .; then \
		echo "✗ Tag $$TAG already exists — bump version in pyproject.toml first"; \
		exit 1; \
	fi; \
	echo ""; \
	echo "How do you want to write release notes?"; \
	echo "  1) AI-generated"; \
	echo "  2) Write manually (opens $$EDITOR)"; \
	read -p "Choice [1/2]: " CHOICE; \
	if [ "$$CHOICE" = "2" ]; then \
		TMPFILE=$$(mktemp /tmp/zen_release_XXXXXX.md); \
		echo "# Release notes for $$TAG" > "$$TMPFILE"; \
		echo "" >> "$$TMPFILE"; \
		$${EDITOR:-vi} "$$TMPFILE"; \
		NOTES=$$(cat "$$TMPFILE"); \
		rm -f "$$TMPFILE"; \
		if [ -z "$$NOTES" ]; then echo "✗ Empty notes — aborting."; exit 1; fi; \
	else \
		echo "Generating release notes with AI..."; \
		NOTES=$$($(PYTHON) tools/generate_release_notes.py "$$VERSION") || exit 1; \
	fi; \
	echo ""; \
	echo "┌── Release Notes ($$TAG) ──"; \
	echo "$$NOTES" | sed 's/^/│ /'; \
	echo "└──────────────────────────"; \
	echo ""; \
	read -p "Create release $$TAG with these notes? [y/N] " CONFIRM; \
	if [ "$$CONFIRM" = "y" ] || [ "$$CONFIRM" = "Y" ]; then \
		NOTES_B64=$$(echo "$$NOTES" | base64 -w 0 2>/dev/null || echo "$$NOTES" | base64 2>/dev/null); \
		gh workflow run release.yml --ref main -f "notes_b64=$$NOTES_B64"; \
		echo "✓ Release workflow dispatched"; \
		echo "  Watch: $$(gh browse -n)/actions/workflows/release.yml"; \
	else \
		echo "Cancelled."; \
	fi
