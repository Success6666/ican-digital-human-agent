#!/usr/bin/env bash
set -eu
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ARTIFACT="$ROOT/tmp-docs/v0.1.50-pi-agent-artifacts"
cp "$ARTIFACT/MODIFIED_FILE.py" "$ARTIFACT/ROLLBACK_TEST_FILE.py"
cp "$ARTIFACT/BASELINE_FILE.py" "$ARTIFACT/ROLLBACK_TEST_FILE.py"
test "$(sha256sum "$ARTIFACT/ROLLBACK_TEST_FILE.py" | awk '{print $1}')" = "$(sha256sum "$ARTIFACT/BASELINE_FILE.py" | awk '{print $1}')"
cp "$ARTIFACT/MODIFIED_FILE.py" "$ARTIFACT/ROLLBACK_TEST_FILE.py"
test "$(sha256sum "$ARTIFACT/ROLLBACK_TEST_FILE.py" | awk '{print $1}')" = "$(sha256sum "$ARTIFACT/MODIFIED_FILE.py" | awk '{print $1}')"
printf 'rollback test passed\n'
