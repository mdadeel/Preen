#!/usr/bin/env bash
# Build Preen as an AppImage (AppDir + appimagetool).
# Uses the host's Python and GTK rather than bundling a runtime; the host must
# provide the required Python, GTK and PyGObject packages.
# Result: dist/Preen-<version>-x86_64.AppImage
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION=$(python3 -c "import sys; sys.path.insert(0,'.'); import preen_tool; print(preen_tool.__version__)")
TOOL=${APPIMAGETOOL:-/tmp/appimagetool-x86_64.AppImage}
APPDIR=$(mktemp -d)
OUTPUT_DIR=$(mktemp -d)
trap 'rm -rf "$APPDIR" "$OUTPUT_DIR"' EXIT

if [ ! -x "$TOOL" ]; then
  if [ -n "${APPIMAGETOOL:-}" ]; then
    echo "APPIMAGETOOL is not executable: $TOOL" >&2
    exit 1
  fi
  echo "Downloading appimagetool without checksum verification; prefer a trusted APPIMAGETOOL."
  DOWNLOAD="$OUTPUT_DIR/appimagetool-x86_64.AppImage"
  curl --fail --location --silent --show-error -o "$DOWNLOAD" \
    https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
  chmod +x "$DOWNLOAD"
  TOOL=$DOWNLOAD
fi

# --- Python package ---
SITE="$APPDIR/usr/lib/python3/dist-packages"
install -d "$SITE/preen_tool/backend" "$SITE/preen_tool/config"
cp preen_tool/*.py "$SITE/preen_tool/"
cp preen_tool/backend/*.py "$SITE/preen_tool/backend/"
cp preen_tool/config/*.json "$SITE/preen_tool/config/"
cp -R preen_tool/assets "$SITE/preen_tool/assets"
find "$APPDIR" -name '__pycache__' -type d -exec rm -rf {} +

# --- Launcher + AppRun ---
install -d "$APPDIR/usr/bin"
cat > "$APPDIR/usr/bin/preen" <<'EOF'
#!/usr/bin/python3
import sys
from preen_tool.app import main
sys.exit(main())
EOF
chmod 755 "$APPDIR/usr/bin/preen"

cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
export PYTHONPATH="$HERE/usr/lib/python3/dist-packages${PYTHONPATH:+:$PYTHONPATH}"
exec python3 "$HERE/usr/bin/preen" "$@"
EOF
chmod 755 "$APPDIR/AppRun"

# --- Desktop entry + icons ---
install -d "$APPDIR/usr/share/applications" \
          "$APPDIR/usr/share/icons/hicolor/256x256/apps"
install -m 644 data/io.github.mdadeel.Preen.desktop "$APPDIR/io.github.mdadeel.Preen.desktop"
install -m 644 data/io.github.mdadeel.Preen.desktop "$APPDIR/usr/share/applications/io.github.mdadeel.Preen.desktop"
install -m 644 preen_tool/assets/preen.png "$APPDIR/preen.png"
install -m 644 preen_tool/assets/preen.png "$APPDIR/usr/share/icons/hicolor/256x256/apps/preen.png"
ln -sf preen.png "$APPDIR/.DirIcon"

# License, privacy information and documentation travel with the AppImage.
./packaging/stage_docs.sh "$APPDIR/usr/share/doc/preen"

# Build to a temporary path so a failed or stubbed tool cannot leave a stale
# artifact looking like a successful build.
# mktemp -d creates the AppDir root with mode 0700; appimagetool requires the
# staged tree to be readable and executable by everyone it will run as.
chmod 755 "$APPDIR"
OUTPUT="$OUTPUT_DIR/Preen-${VERSION}-x86_64.AppImage"
ARCH=x86_64 "$TOOL" --appimage-extract-and-run "$APPDIR" "$OUTPUT"
if [ ! -s "$OUTPUT" ] || [ ! -x "$OUTPUT" ]; then
  echo "AppImage build failed: the tool did not create an executable artifact." >&2
  exit 1
fi
python3 - "$OUTPUT" <<'PY'
import sys
with open(sys.argv[1], "rb") as image:
    header = image.read(11)
if header[:4] != b"\x7fELF" or header[8:11] != b"AI\x02":
    sys.exit("AppImage build failed: invalid type-2 AppImage header")
PY
REPORTED_VERSION=$("$OUTPUT" --appimage-extract-and-run --version)
if [ "$REPORTED_VERSION" != "$VERSION" ]; then
  echo "AppImage build failed: expected version $VERSION, got $REPORTED_VERSION" >&2
  exit 1
fi
mkdir -p dist
install -m 755 "$OUTPUT" "dist/Preen-${VERSION}-x86_64.AppImage"
echo "Built and smoke-tested dist/Preen-${VERSION}-x86_64.AppImage"
