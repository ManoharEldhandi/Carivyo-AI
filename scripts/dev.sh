#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BOOTSTRAP_TOKEN="$("$ROOT/.venv/bin/python" -c 'import secrets; print(secrets.token_urlsafe(32))')"
export CARIVYO_BOOTSTRAP_TOKEN="$BOOTSTRAP_TOKEN"
export VITE_CARIVYO_BOOTSTRAP_TOKEN="$BOOTSTRAP_TOKEN"

check_port() {
  "$ROOT/.venv/bin/python" - "$1" <<'PY'
import socket
import sys

port = int(sys.argv[1])
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("127.0.0.1", port))
    except OSError:
        raise SystemExit(1)
PY
}

for port in 8420 5173; do
  if ! check_port "$port"; then
    echo "Carivyo cannot start because 127.0.0.1:$port is already in use." >&2
    echo "Stop the older Carivyo terminal with Ctrl-C, then run make dev again." >&2
    exit 1
  fi
done

BACKEND_PID=""
FRONTEND_PID=""

terminate_tree() {
  local parent="$1"
  local child
  for child in $(pgrep -P "$parent" 2>/dev/null || true); do
    terminate_tree "$child"
  done
  kill "$parent" 2>/dev/null || true
}

cleanup() {
  [[ -n "$FRONTEND_PID" ]] && terminate_tree "$FRONTEND_PID"
  [[ -n "$BACKEND_PID" ]] && terminate_tree "$BACKEND_PID"
}
trap cleanup EXIT INT TERM

"$ROOT/.venv/bin/uvicorn" app.main:app \
  --app-dir "$ROOT/backend" \
  --host 127.0.0.1 \
  --port 8420 \
  --reload &
BACKEND_PID="$!"

npm --prefix "$ROOT/frontend" run dev -- --host 127.0.0.1 --strictPort &
FRONTEND_PID="$!"

LAUNCH_URL="http://127.0.0.1:5173/"
echo "Opening Carivyo: $LAUNCH_URL"

services_ready() {
  "$ROOT/.venv/bin/python" - <<'PY'
import urllib.request

for url in ("http://127.0.0.1:5173/", "http://127.0.0.1:8420/health"):
    with urllib.request.urlopen(url, timeout=0.4) as response:
        if response.status != 200:
            raise SystemExit(1)
PY
}

if [[ "${CARIVYO_NO_OPEN:-0}" != "1" ]]; then
  (
    for _ in {1..80}; do
      if ! kill -0 "$BACKEND_PID" 2>/dev/null || ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
        echo "Carivyo stopped before startup completed. Review the terminal error above." >&2
        break
      fi
      if services_ready >/dev/null 2>&1; then
        if command -v open >/dev/null 2>&1; then
          open "$LAUNCH_URL"
        elif command -v xdg-open >/dev/null 2>&1; then
          xdg-open "$LAUNCH_URL" >/dev/null 2>&1
        fi
        break
      fi
      sleep 0.25
    done
  ) &
fi

while kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$FRONTEND_PID" 2>/dev/null; do
  sleep 0.5
done

echo "A Carivyo service stopped. The remaining service is being closed." >&2
exit 1
