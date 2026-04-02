#!/bin/bash
# build_appimage.sh — Build a Zen IDE AppImage for Linux
# Usage: ./tools/build_appimage.sh
#
# Prerequisites:
#   - make install-py (venv + all dependencies including build tools)
#   - System GTK4 deps installed (make install-system-deps)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
BUILD_DIR="${PROJECT_DIR}/build"
DIST_DIR="${PROJECT_DIR}/dist"
APPDIR="${BUILD_DIR}/AppDir"
APPIMAGE_TOOL="${BUILD_DIR}/appimagetool"
ARCH="$(uname -m)"

APP_VERSION=$(grep '^version' "${PROJECT_DIR}/pyproject.toml" | head -1 | sed 's/.*"\(.*\)"/\1/')
APPIMAGE_NAME="Zen_IDE-${APP_VERSION}-${ARCH}.AppImage"

echo "╔══════════════════════════════════════════════╗"
echo "║  Building Zen IDE AppImage (${ARCH})            ║"
echo "║  Version: ${APP_VERSION}                              ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

# ── Step 1: Run PyInstaller ──────────────────────────────────────────

echo "▸ Step 1/4: Running PyInstaller..."
cd "${PROJECT_DIR}"
rm -rf "${BUILD_DIR}" "${DIST_DIR}"
uv run pyinstaller "Zen IDE.linux.spec" --noconfirm
echo "  ✓ PyInstaller build complete"

# ── Step 2: Assemble AppDir ──────────────────────────────────────────

echo "▸ Step 2/4: Assembling AppDir..."
rm -rf "${APPDIR}"
mkdir -p "${APPDIR}"

# Copy PyInstaller output (onedir bundle)
cp -a "${DIST_DIR}/zen-ide" "${APPDIR}/zen-ide"

# AppRun launcher
cp "${SCRIPT_DIR}/appimage/AppRun" "${APPDIR}/AppRun"
chmod +x "${APPDIR}/AppRun"

# Desktop file
cp "${SCRIPT_DIR}/appimage/zen-ide.desktop" "${APPDIR}/zen-ide.desktop"

# Icon (required at AppDir root for appimagetool)
cp "${PROJECT_DIR}/zen_icon.png" "${APPDIR}/zen-ide.png"

# Icon in standard location for desktop integration
mkdir -p "${APPDIR}/share/icons/hicolor/256x256/apps"
cp "${PROJECT_DIR}/zen_icon.png" "${APPDIR}/share/icons/hicolor/256x256/apps/zen-ide.png"

# Strip debug symbols from bundled .so files
echo "  Stripping debug symbols..."
find "${APPDIR}/zen-ide" -type f -name '*.so' -exec strip --strip-debug {} 2>/dev/null \; || true
find "${APPDIR}/zen-ide" -type f -name '*.so.*' -exec strip --strip-debug {} 2>/dev/null \; || true

echo "  ✓ AppDir assembled"

# ── Step 3: Download appimagetool if needed ──────────────────────────

echo "▸ Step 3/4: Checking appimagetool..."
if [ ! -x "${APPIMAGE_TOOL}" ]; then
    echo "  Downloading appimagetool..."
    TOOL_URL="https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-${ARCH}.AppImage"
    curl -fsSL "${TOOL_URL}" -o "${APPIMAGE_TOOL}"
    chmod +x "${APPIMAGE_TOOL}"
    echo "  ✓ appimagetool downloaded"
else
    echo "  ✓ appimagetool found (cached)"
fi

# ── Step 4: Build AppImage ───────────────────────────────────────────

echo "▸ Step 4/4: Building AppImage..."
ARCH="${ARCH}" "${APPIMAGE_TOOL}" "${APPDIR}" "${DIST_DIR}/${APPIMAGE_NAME}" --no-appstream 2>&1 || {
    # Fallback: try with --appimage-extract-and-run for environments without FUSE
    echo "  Retrying with --appimage-extract-and-run (no FUSE)..."
    ARCH="${ARCH}" "${APPIMAGE_TOOL}" --appimage-extract-and-run "${APPDIR}" "${DIST_DIR}/${APPIMAGE_NAME}" --no-appstream
}

chmod +x "${DIST_DIR}/${APPIMAGE_NAME}"

echo ""
echo "════════════════════════════════════════════════"
echo "✓ AppImage built successfully!"
echo "  Output: dist/${APPIMAGE_NAME}"
echo "  Size:   $(du -sh "${DIST_DIR}/${APPIMAGE_NAME}" | cut -f1)"
echo ""
echo "  Run it:  ./dist/${APPIMAGE_NAME}"
echo "════════════════════════════════════════════════"
