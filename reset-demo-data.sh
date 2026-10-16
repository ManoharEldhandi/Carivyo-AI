#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="$ROOT/.carivyo"

if lsof -nP -iTCP:8420 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Stop Carivyo before resetting its local data." >&2
  exit 1
fi

rm -rf \
  "$DATA_DIR/artifacts" \
  "$DATA_DIR/backups" \
  "$DATA_DIR/enhancv-browser-profile" \
  "$DATA_DIR/runtime" \
  "$DATA_DIR/carivyo.sqlite3" \
  "$DATA_DIR/carivyo.sqlite3-shm" \
  "$DATA_DIR/carivyo.sqlite3-wal"

echo "Carivyo generated profile, job, chat, resume, report, and backup data has been reset."
echo "The local Codex CLI in .carivyo/tools/ was preserved."