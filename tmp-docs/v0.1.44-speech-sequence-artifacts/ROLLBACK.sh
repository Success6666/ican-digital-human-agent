#!/usr/bin/env bash
set -euo pipefail

target="${1:?usage: ROLLBACK.sh <modified-copy>}"
baseline="$(dirname "$0")/baseline-mofaRuntime.ts"
cp "$baseline" "$target"
cmp -s "$baseline" "$target"
printf 'rollback-restored=%s\n' "$target"
