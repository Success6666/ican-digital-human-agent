#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_DIR="${1:-$ROOT/rollback-copy}"
BASELINE="$ROOT/baseline-audio_handlers.py"
TARGET="$TARGET_DIR/audio_handlers.py"

mkdir -p "$TARGET_DIR"
cp "$BASELINE" "$TARGET"
cmp -s "$BASELINE" "$TARGET"
echo "ROLLBACK_OK: restored $TARGET"
