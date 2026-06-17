#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VERSION="$(tr -d '[:space:]' < "$ROOT/VERSION")"
DIST="$ROOT/dist"
PKG="jetson-yolo-pipeline-docs-$VERSION"
export COPYFILE_DISABLE=1

mkdir -p "$DIST"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

rsync -a \
  --exclude '.git' \
  --exclude '.DS_Store' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude 'dist' \
  --exclude 'webui/runtime' \
  "$ROOT/" "$TMP/$PKG/"

tar --no-xattrs -C "$TMP" -czf "$DIST/$PKG.tar.gz" "$PKG"
echo "$DIST/$PKG.tar.gz"
