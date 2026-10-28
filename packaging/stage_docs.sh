#!/usr/bin/env bash
# Stage the same documentation and licence notices into each native package.
set -euo pipefail
if [ "$#" -ne 1 ] || [ -z "$1" ]; then
  echo "Usage: $0 DESTINATION" >&2
  exit 2
fi
DEST=$1
cd "$(dirname "$0")/.."
install -d "$DEST/docs/images" "$DEST/preen_tool/assets/brand"
install -m 644 README.md LICENSE CHANGELOG.md CONTRIBUTING.md CODE_OF_CONDUCT.md \
  PRIVACY.md SECURITY.md THIRD_PARTY_NOTICES.md "$DEST/"
install -m 644 docs/*.md docs/*.example "$DEST/docs/"
install -m 644 docs/images/*.png "$DEST/docs/images/"
install -m 644 preen_tool/assets/brand/*.md "$DEST/preen_tool/assets/brand/"
