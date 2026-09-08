#!/usr/bin/env bash
set -euo pipefail

artifact_dir="$(cd "$(dirname "$0")" && pwd)"
target="${1:-$artifact_dir/ROLLBACK_TEST_FILE.ts}"
expected="a15276097bb64149a126b427eb918e7b75244424220241e75a7119c029b7039f"

cp "$artifact_dir/BASELINE_FILE.ts" "$target"
actual="$(sha256sum "$target" | awk '{print $1}')"
if [[ "$actual" != "$expected" ]]; then
  echo "ROLLBACK_FAILED expected=$expected actual=$actual" >&2
  exit 1
fi
echo "ROLLBACK_OK sha256=$actual"
