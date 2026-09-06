#!/usr/bin/env bash
set -euo pipefail

target="${1:?target copy is required}"
baseline="${2:?baseline copy is required}"
cp "$baseline" "$target"
cmp -s "$target" "$baseline"
printf 'rollback restored: %s\n' "$target"
