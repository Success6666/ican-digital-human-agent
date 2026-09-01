#!/usr/bin/env sh
set -eu
base_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
target=${1:-"$base_dir/rollback-copy.ts"}
cp "$base_dir/mofa-runtime.original.ts" "$target"
cmp "$base_dir/mofa-runtime.original.ts" "$target"
printf 'rollback-restored=%s\n' "$target"
