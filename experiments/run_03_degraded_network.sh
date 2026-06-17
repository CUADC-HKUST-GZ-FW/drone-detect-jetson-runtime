#!/usr/bin/env bash
set -euo pipefail

CONFIG="configs/degraded_policy.example.json"
APPLY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config) CONFIG="$2"; shift 2 ;;
    --apply) APPLY=1; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

cd "$(dirname "${BASH_SOURCE[0]}")/.."
if [[ "$APPLY" -eq 1 ]]; then
  python3 scripts/tc_apply.py --config "$CONFIG" --apply --yes --allow-ssh-interface
else
  python3 scripts/tc_apply.py --config "$CONFIG" --dry-run
fi

