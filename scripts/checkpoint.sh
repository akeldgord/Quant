#!/usr/bin/env bash
# Wrapper around `argus checkpoint bundle`. Usage: scripts/checkpoint.sh <phase> [checkpoint_file]
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

PHASE="${1:?usage: checkpoint.sh <phase> [checkpoint_text_file]}"
CHECKPOINT_FILE="${2:-}"

if [ -n "$CHECKPOINT_FILE" ]; then
  uv run argus checkpoint bundle --phase "$PHASE" --checkpoint-file "$CHECKPOINT_FILE"
else
  uv run argus checkpoint bundle --phase "$PHASE"
fi
