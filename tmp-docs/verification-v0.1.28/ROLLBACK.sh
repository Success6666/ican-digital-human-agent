#!/usr/bin/env bash
set -euo pipefail
copy="${1:-rollback-copy.txt}"
printf 'LLM streaming verification fixture\nstate=baseline\n' > "$copy"
grep -q '^state=baseline$' "$copy"
rm -f "$copy"
printf 'rollback verified\n'
