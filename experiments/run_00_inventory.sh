#!/usr/bin/env bash
set -euo pipefail

NODE="${1:-jetson}"
cd "$(dirname "${BASH_SOURCE[0]}")/.."
bash scripts/inventory.sh --node "$NODE"

