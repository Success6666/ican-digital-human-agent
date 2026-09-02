#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
BASELINE="$ROOT/baseline-mofaRuntime.ts"
COPY="$ROOT/rollback-copy-mofaRuntime.ts"

cp "$BASELINE" "$COPY"
cmp -s "$BASELINE" "$COPY"
printf 'ROLLBACK_OK baseline restored to verification copy: %s\n' "$COPY"
