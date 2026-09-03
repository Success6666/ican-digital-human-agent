#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ARTIFACT="$ROOT/tmp-docs/v0.1.52-ttsa-return-error-artifacts"
cp "$ARTIFACT/BASELINE_FILE.ts" "$ARTIFACT/ROLLBACK_TEST_FILE.ts"
grep -q "phase: 'error'" "$ARTIFACT/ROLLBACK_TEST_FILE.ts"
echo 'rollback source restored on copy'
