#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ARTIFACT="$ROOT/tmp-docs/v0.1.51-session-start-artifacts"
cp "$ARTIFACT/BASELINE_FILE.py" "$ARTIFACT/ROLLBACK_TEST_FILE.py"
if ! grep -q 'wss://nebula-agent.xingyun3d.com/user/v1/ttsa/session' "$ARTIFACT/ROLLBACK_TEST_FILE.py"; then
  echo 'rollback source check failed' >&2
  exit 1
fi
echo 'rollback source restored on copy'