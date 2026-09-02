#!/usr/bin/env bash
set -euo pipefail
baseline="$1"
target="$2"
cp -- "$baseline" "$target"
baseline_hash=$(sha256sum -- "$baseline" | awk '{print toupper($1)}')
rollback_hash=$(sha256sum -- "$target" | awk '{print toupper($1)}')
if [[ "$baseline_hash" != "$rollback_hash" ]]; then
  echo "restored=false baseline_hash=$baseline_hash rollback_hash=$rollback_hash"
  exit 1
fi
echo "restored=$target baseline_hash=$baseline_hash rollback_hash=$rollback_hash restored=True rollback_compare_exit=0"
