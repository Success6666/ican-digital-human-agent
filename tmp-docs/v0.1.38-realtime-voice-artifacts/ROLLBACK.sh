#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE="$ROOT/baseline/audio_handlers.py"
TARGET="${1:-$ROOT/rollback-copy/audio_handlers.py}"
mkdir -p "$(dirname "$TARGET")"
cp "$SOURCE" "$TARGET"
test "$(sha256sum "$SOURCE" | awk '{print $1}')" = "$(sha256sum "$TARGET" | awk '{print $1}')"
printf 'rollback restored %s\n' "$TARGET"
