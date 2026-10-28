#!/usr/bin/env bash
# Build version-matched release files from a clean checkout.
# Usage: ./packaging/build_release.sh [--skip-appimage] [OUTPUT_DIRECTORY]
set -euo pipefail
cd "$(dirname "$0")/.."

SKIP_APPIMAGE=0
if [ "${1:-}" = "--skip-appimage" ]; then
  SKIP_APPIMAGE=1
  shift
fi
if [ "$#" -gt 1 ]; then
  echo "Usage: $0 [--skip-appimage] [OUTPUT_DIRECTORY]" >&2
  exit 2
fi

if [ -n "$(git status --porcelain --untracked-files=normal)" ]; then
  echo "Release builds require a clean tracked and untracked working tree." >&2
  exit 1
fi
VERSION=$(python3 -c 'import preen_tool; print(preen_tool.__version__)')
SOURCE_REF=${PREEN_SOURCE_REF:-HEAD}
SOURCE_TREE=$(git rev-parse --verify --end-of-options "$SOURCE_REF^{tree}")
WORKING_TREE=$(git rev-parse --verify 'HEAD^{tree}')
if [ "$SOURCE_TREE" != "$WORKING_TREE" ]; then
  echo "Release source reference does not match the checkout's file tree." >&2
  exit 1
fi
python3 - "$VERSION" <<'PY'
import pathlib
import re
import sys
version = sys.argv[1]
project = pathlib.Path("pyproject.toml").read_text(encoding="utf-8")
section = project.split("[project]", 1)[1].split("[", 1)[0]
match = re.search(r'^version\s*=\s*"([^"\n]+)"', section, re.M)
debian = pathlib.Path("debian/changelog").read_text(encoding="utf-8").splitlines()[0]
if not match or match.group(1) != version or debian != f"preen ({version}) stable; urgency=medium":
    sys.exit("Version mismatch between the app, pyproject.toml and Debian changelog")
PY

DEST=${1:-"dist/release-$VERSION"}
DEST=$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$DEST")
mkdir -p "$DEST"
if [ -n "$(find "$DEST" -mindepth 1 -maxdepth 1 -print -quit)" ]; then
  echo "Release destination must be empty: $DEST" >&2
  exit 1
fi

printf 'Building Preen %s from tree %s\n' "$VERSION" "$SOURCE_TREE"
git archive --format=zip --prefix="preen-$VERSION/" \
  --output="$DEST/preen-$VERSION-source.zip" "$SOURCE_REF"
# setuptools.build_meta mutates sys.argv. Use separate interpreters so a
# completed sdist build cannot redirect the following wheel to the wrong path.
python3 - "$DEST" <<'PY'
import sys
import setuptools.build_meta as backend
backend.build_sdist(sys.argv[1])
PY
python3 - "$DEST" <<'PY'
import sys
import setuptools.build_meta as backend
backend.build_wheel(sys.argv[1])
PY
./packaging/build_deb.sh
install -m 644 "dist/preen_${VERSION}_all.deb" "$DEST/preen_${VERSION}_all.deb"

FILES=("preen-$VERSION-source.zip" "preen-$VERSION.tar.gz"
       "preen-$VERSION-py3-none-any.whl" "preen_${VERSION}_all.deb")
if [ "$SKIP_APPIMAGE" -eq 0 ]; then
  ./packaging/build_appimage.sh
  install -m 755 "dist/Preen-${VERSION}-x86_64.AppImage" \
    "$DEST/Preen-${VERSION}-x86_64.AppImage"
  FILES+=("Preen-${VERSION}-x86_64.AppImage")
else
  echo "AppImage skipped by request; this is not a complete binary release." >&2
fi

python3 - "$DEST" "$VERSION" <<'PY'
import email.parser
import pathlib
import tarfile
import zipfile
import sys
root, version = pathlib.Path(sys.argv[1]), sys.argv[2]
required = ("README.md", "LICENSE", "PRIVACY.md", "SECURITY.md",
            "docs/images/preen-dashboard.png", "docs/images/preen-manage-apps.png")
with zipfile.ZipFile(root / f"preen-{version}-source.zip") as archive:
    if archive.testzip():
        sys.exit("Source ZIP contains a corrupt entry")
    names = set(archive.namelist())
    for name in required:
        if f"preen-{version}/{name}" not in names:
            sys.exit(f"Source ZIP missing {name}")
with tarfile.open(root / f"preen-{version}.tar.gz", "r:gz") as archive:
    names = set(archive.getnames())
    for name in required:
        if f"preen-{version}/{name}" not in names:
            sys.exit(f"Source archive missing {name}")
with zipfile.ZipFile(root / f"preen-{version}-py3-none-any.whl") as archive:
    if archive.testzip():
        sys.exit("Wheel contains a corrupt entry")
    metadata_name = next(name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
    metadata = email.parser.BytesParser().parsebytes(archive.read(metadata_name))
    if metadata["Version"] != version:
        sys.exit("Wheel metadata does not match the release version")
    if not any(name.endswith(".dist-info/LICENSE") or name.endswith(".dist-info/licenses/LICENSE")
               for name in archive.namelist()):
        sys.exit("Wheel is missing the project license")
PY
if [ "$(dpkg-deb -f "$DEST/preen_${VERSION}_all.deb" Version)" != "$VERSION" ]; then
  echo "Debian package version does not match $VERSION." >&2
  exit 1
fi
EXTRACT=$(mktemp -d)
trap 'rm -rf "$EXTRACT"' EXIT
dpkg-deb -x "$DEST/preen_${VERSION}_all.deb" "$EXTRACT"
for item in LICENSE PRIVACY.md SECURITY.md THIRD_PARTY_NOTICES.md; do
  test -s "$EXTRACT/usr/share/doc/preen/$item" || {
    echo "Debian package is missing $item." >&2; exit 1;
  }
done
DEB_VERSION=$(cd "$EXTRACT" && PYTHONPATH="$EXTRACT/usr/lib/python3/dist-packages" \
  python3 -m preen_tool.app --version)
if [ "$DEB_VERSION" != "$VERSION" ]; then
  echo "Extracted Debian package reported unexpected version: $DEB_VERSION" >&2
  exit 1
fi
(
  cd "$DEST"
  sha256sum "${FILES[@]}" > SHA256SUMS
  sha256sum --check SHA256SUMS
)
printf 'Release files: %s\n' "$DEST"
