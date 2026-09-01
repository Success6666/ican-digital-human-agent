#!/usr/bin/env sh
set -eu

target="${1:?usage: ROLLBACK.sh <modified-copy>}"
baseline="$(dirname "$0")/baseline/evaluation_service.py"
cp "$baseline" "$target"
printf 'restored=%s\n' "$target"
