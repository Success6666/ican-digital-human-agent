#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cp "$ROOT/baseline-ConversationDrawer.tsx" "$ROOT/rollback-copy-ConversationDrawer.tsx"
cmp -s "$ROOT/baseline-ConversationDrawer.tsx" "$ROOT/rollback-copy-ConversationDrawer.tsx"
printf 'ROLLBACK_OK baseline restored to verification copy: %s\n' "$ROOT/rollback-copy-ConversationDrawer.tsx"
