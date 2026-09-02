#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 BASELINE_FILE TARGET_FILE" >&2
  exit 2
fi

cp -- "$1" "$2"
echo "restored=$2"
