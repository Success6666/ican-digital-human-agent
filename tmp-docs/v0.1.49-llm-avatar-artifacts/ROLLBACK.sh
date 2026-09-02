#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TARGET="$ROOT/tmp-docs/v0.1.49-llm-avatar-artifacts/ROLLBACK_TEST_FILE.py"
cp "$ROOT/tmp-docs/v0.1.49-llm-avatar-artifacts/MODIFIED_FILE.py" "$TARGET"
cp "$ROOT/tmp-docs/v0.1.49-llm-avatar-artifacts/BASELINE_FILE.py" "$TARGET"
test "$(sha256sum "$TARGET" | awk '{print $1}')" = "$(sha256sum "$ROOT/tmp-docs/v0.1.49-llm-avatar-artifacts/BASELINE_FILE.py" | awk '{print $1}')"
echo "rollback restored baseline: $TARGET"
