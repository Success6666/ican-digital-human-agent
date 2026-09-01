#!/usr/bin/env sh
set -eu
base_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
target=${1:-"$base_dir/rollback-copy.py"}
cp "$base_dir/llm-client.modified.py" "$target"
cp "$base_dir/llm-client.original.py" "$target"
cmp "$base_dir/llm-client.original.py" "$target"
printf 'rollback-restored=%s\n' "$target"
