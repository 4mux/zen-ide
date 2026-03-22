# Dist Packaging — macOS App Bundle & Linux AppImage

**Created_at:** 2026-03-17  
**Updated_at:** 2026-03-22  
**Status:** Active  
**Goal:** Document the `make dist` packaging pipeline for macOS and Linux, common pitfalls, and the checklist for adding new dependencies  
**Scope:** `Zen IDE.spec`, `Zen IDE.linux.spec`, `Makefile` (dist target), `tools/trim_icu_data.py`, `tools/build_appimage.sh`, `tools/appimage/`, `tools/pyinstaller_hooks/`  

---

## Overview

`make dist` produces a standalone distributable for the current platform:

- **macOS:** `.app` bundle using PyInstaller + codesigning
- **Linux:** `.AppImage` using PyInstaller + appimagetool

### macOS Pipeline Steps

```
make dist (macOS)
  ├─ 1. PyInstaller  →  Freeze Python + deps into .app bundle
  ├─ 2. strip -x     →  Remove debug symbols from .dylib/.so files
  ├─ 3. trim_icu_data →  Shrink libicudata (locale reduction, ~25 MB saved)
  ├─ 4. codesign      →  Re-sign all binaries + the .app bundle
  └─ 5. cp to /Applications
```

### Linux Pipeline Steps

```
make dist (Linux)
  ├─ 1. PyInstaller  →  Freeze Python + deps into onedir bundle
  ├─ 2. Assemble AppDir (bundle + .desktop + icon + AppRun)
  ├─ 3. strip         →  Remove debug symbols from .so files
  ├─ 4. appimagetool  →  Compress AppDir into .AppImage
  └─ 5. Output: dist/Zen_IDE-<version>-<arch>.AppImage
```

---

## Adding a New Python Dependency

PyInstaller performs static analysis to discover imports. It frequently **misses**:

- Packages imported only at runtime or behind `if` guards
- Packages with C extensions (e.g., `yaml`, `cmarkgfm`, `watchfiles`)
- Packages imported via `importlib` or string-based imports
- Sub-modules not referenced directly in top-level code

### Checklist

1. **Add to `pyproject.toml`** dependencies as usual.
2. **Add to `hiddenimports`** in `Zen IDE.spec`. List the top-level module **and all sub-modules** that have C extensions or that PyInstaller warns about.
   ```python
   # Example: adding PyYAML
   hiddenimports=[
       ...
       'yaml',
       'yaml._yaml',       # C extension
       'yaml.loader',
       'yaml.dumper',
       # ... all yaml.* submodules
   ]
   ```
3. **Check the `excludes` list.** If your new dependency imports a stdlib module that we exclude (e.g., `email`, `multiprocessing`), either remove it from `excludes` or guard the import. Current excludes:
   ```
   tkinter, unittest, pydoc, pydoc_data, PIL, Pillow,
   multiprocessing, xmlrpc, lib2to3, ensurepip,
   idlelib, turtledemo, turtle, doctest, test
   ```
4. **Build and test:**
   ```bash
   make dist
   "./dist/Zen IDE.app/Contents/MacOS/zen-launcher" 2>&1
   ```
5. **Verify the module is actually bundled:**
   ```bash
   find "dist/Zen IDE.app/Contents/Resources" -name "your_module*" -type d
   ```

### Guard Optional Imports

If a feature uses a package that may fail to bundle, **wrap the import** so it degrades gracefully instead of crashing the entire app:

```python
# BAD — top-level import crashes the app if yaml is missing
from editor.preview.openapi_preview import OpenApiPreview

# GOOD — guarded import, feature degrades gracefully
try:
    from editor.preview.openapi_preview import OpenApiPreview
except ImportError:
    OpenApiPreview = None
```

This is especially important for preview modules, optional file-type handlers, and any import triggered by opening user files.

---

## Stdlib Excludes — Why and What to Watch

We exclude unused stdlib modules to reduce bundle size. **Before adding a new exclude**, grep the entire dependency tree — not just `src/`:

```bash
# Check if any dependency (including transitive) uses the module
uv run python3 -c "import email; print('used')"
```

**Known gotcha:** `pkg_resources` (used by many packages) depends on the `email` module. Excluding `email` breaks `pkg_resources` imports at runtime.

**Rule:** If unsure whether a stdlib module is safe to exclude, **don't exclude it.** The size savings (<1 MB each) are not worth a broken app.

---

## ICU Data Trimming

`tools/trim_icu_data.py` shrinks `libicudata.XX.dylib` from ~32 MB to ~7 MB by removing non-English locale data that a code editor doesn't need.

### What It Keeps

| Category | Examples | Why |
|----------|----------|-----|
| Break iterators (`brkitr/`) | Line/word/sentence break rules | Text segmentation — essential for Pango |
| Transliteration (`translit/`) | Script conversion rules | Used by GTK/Pango internally |
| English collation (`coll/`) | `root.res`, `en.res`, `ucadata.icu` | Sorting/comparison for English text |
| English locales | `en.res`, `en_US.res`, `en_GB.res` | Date/number formatting |
| Normalization (`.nrm`) | NFC/NFD/NFKC/NFKD | Unicode normalization |
| Core ICU data | `cnvalias.icu`, `confusables.cfu`, etc. | Fundamental ICU operations |

### What It Removes

- All non-English locale and collation data (~200 locales)
- Charset converters (Python handles encoding)
- Currency/unit/region display name data
- Rule-based number formatting
- StringPrep profiles

### Symbol Name Gotcha

`genccode` generates the symbol `_icudt78l_dat` (with `l` for little-endian), but `libicuuc` expects `_icudt78_dat` (no endian suffix). The script patches the assembly before compiling. If you see `Symbol not found: _icudt78_dat` errors, this patching has broken — check `rebuild_dylib()` in the script.

### When ICU Version Changes

If Homebrew upgrades ICU (e.g., 78 → 79), update:
1. `tools/trim_icu_data.py` — the `.dat` filename and symbol name references
2. Verify the `__TEXT.__const` section parsing still works (offsets may change)

---

## macOS Platform Quirks

### Cmd+, (Preferences)

When running as a `.app` bundle, the macOS GTK4 backend creates a native menu bar and maps **Cmd+,** to the GAction `app.preferences`. This overrides any custom keybinding for `<Meta>comma`. The app must register a `"preferences"` action on the `Gtk.Application` that calls the settings handler.

This does **not** affect `make run` (dev mode), only the `.app` bundle.

### Code Signing

After any binary modification (stripping, ICU trimming), all `.dylib` and `.so` files must be re-signed:

```bash
codesign --force --sign - path/to/modified.dylib
codesign --force --deep --sign - --entitlements entitlements.plist "dist/Zen IDE.app"
```

The Makefile `dist` target handles this automatically.

---

## Testing the Dist Build

After `make dist`, always verify **all** of these:

| Check | How |
|-------|-----|
| App launches | `"./dist/Zen IDE.app/Contents/MacOS/zen-launcher"` |
| Terminal works | Open a terminal tab inside the IDE (VTE loads ICU) |
| Settings open | Press Cmd+, — should open `~/.zen_ide/settings.json` with content |
| File tree sorts | Expand a folder — files should be alphabetically ordered |
| Previews work | Open a `.md` file — markdown preview should render |

If the app crashes on launch, check stderr for:
- `ModuleNotFoundError` → missing `hiddenimports` entry
- `Symbol not found` → ICU trimming or stripping issue
- `No module named 'yaml'` (or similar) → dependency not bundled

---

## Linux AppImage

### How It Works

The Linux AppImage bundles the PyInstaller-frozen app into a single executable file that runs on most Linux distributions without installation. The build script (`tools/build_appimage.sh`) orchestrates the entire process.

### Key Files

| File | Purpose |
|------|---------|
| `Zen IDE.linux.spec` | PyInstaller spec for Linux (no Homebrew, no macOS frameworks) |
| `tools/build_appimage.sh` | Build orchestrator — PyInstaller → AppDir → AppImage |
| `tools/appimage/AppRun` | Entry point that sets up GI/GTK environment paths |
| `tools/appimage/zen-ide.desktop` | Freedesktop desktop entry embedded in AppImage |

### AppDir Structure

```
AppDir/
  ├─ AppRun                           # Launcher (sets env vars, execs binary)
  ├─ zen-ide.desktop                  # Desktop integration
  ├─ zen-ide.png                      # App icon (256×256)
  ├─ share/icons/hicolor/256x256/     # Icon in standard location
  └─ zen-ide/                         # PyInstaller onedir output
      ├─ zen-ide                      # Frozen executable
      ├─ gi_typelibs/                 # GObject typelibs
      ├─ lib/gdk-pixbuf-2.0/         # Pixbuf loaders
      ├─ share/glib-2.0/schemas/     # GSettings schemas
      ├─ fonts/resources/             # Bundled fonts
      └─ *.so / *.so.*               # Shared libraries
```

### Environment Variables (set by AppRun)

| Variable | Purpose |
|----------|---------|
| `GI_TYPELIB_PATH` | GObject Introspection typelib lookup |
| `LD_LIBRARY_PATH` | Shared library search path |
| `GSETTINGS_SCHEMA_DIR` | GSettings schema location |
| `XDG_DATA_DIRS` | Icons, themes, mime database |
| `GDK_PIXBUF_MODULE_DIR` | Pixbuf loader modules |

### Building

```bash
# Prerequisites
make install-system-deps   # GTK4 system libraries
make install               # Python venv + all deps

# Build the AppImage
make dist
# → dist/Zen_IDE-0.1.0-x86_64.AppImage

# Run it
./dist/Zen_IDE-0.1.0-x86_64.AppImage
```

### Adding Dependencies (Linux-specific)

When adding a new Python or native dependency:

1. Add to `pyproject.toml` as usual
2. Add to `hiddenimports` in **both** `Zen IDE.spec` (macOS) **and** `Zen IDE.linux.spec` (Linux)
3. No `extra_binaries` needed on Linux — PyInstaller auto-detects `.so` files from system paths
4. Build and test: `make dist && ./dist/Zen_IDE-*.AppImage`

### Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `ModuleNotFoundError` on launch | Missing `hiddenimports` | Add module to `Zen IDE.linux.spec` |
| GTK warnings / no theme | Missing GSettings schemas | Check `GSETTINGS_SCHEMA_DIR` in AppRun |
| No icons rendering | Missing icon theme | Verify `hooksconfig.gi.icons` includes `Adwaita` |
| `cannot open shared object` | Missing `.so` in bundle | PyInstaller missed it — add to `binaries` in spec |
| FUSE error running AppImage | Host lacks FUSE | Run with `--appimage-extract-and-run` flag |

### Desktop Integration (without AppImage)

To install just the `.desktop` shortcut pointing at your dev checkout (no AppImage):

```bash
make install-desktop
```

---

## Quick Reference

| Task | Where to Change |
|------|-----------------|
| Add Python dependency | `pyproject.toml` + `Zen IDE.spec` + `Zen IDE.linux.spec` `hiddenimports` |
| Add native library (macOS) | `Zen IDE.spec` `extra_binaries` |
| Add GObject typelib (macOS) | `Zen IDE.spec` `extra_typelibs` |
| Add data files | Both `.spec` files `datas` |
| Exclude stdlib module | Both `.spec` files `excludes` (verify no transitive deps first) |
| Add PyInstaller hook | `tools/pyinstaller_hooks/hook-<module>.py` |
| Adjust ICU trimming (macOS) | `tools/trim_icu_data.py` `KEEP_*` sets |
| macOS app metadata | `Zen IDE.spec` `info_plist` in `BUNDLE()` |
| Linux AppImage config | `tools/appimage/AppRun`, `tools/build_appimage.sh` |
