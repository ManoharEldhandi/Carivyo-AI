#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLS_DIR="$ROOT/.carivyo/tools"
CODEX_BIN=""
DEV_PID=""

cleanup() {
  trap - EXIT INT TERM
  [[ -n "$DEV_PID" ]] && kill "$DEV_PID" 2>/dev/null || true
}

require_command() {
  command -v "$1" >/dev/null || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

resolve_codex() {
  if [[ -x "/Applications/ChatGPT.app/Contents/Resources/codex" ]]; then
    printf '%s\n' "/Applications/ChatGPT.app/Contents/Resources/codex"
    return
  fi
  if command -v codex >/dev/null; then
    command -v codex
    return
  fi
  if [[ ! -x "$TOOLS_DIR/node_modules/.bin/codex" ]]; then
    echo "Installing the project-local Codex CLI..."
    npm install --prefix "$TOOLS_DIR" --no-save @openai/codex@0.162.0
  fi
  printf '%s\n' "$TOOLS_DIR/node_modules/.bin/codex"
}

wait_for_backend() {
  for _ in {1..120}; do
    if curl --fail --silent --max-time 1 http://127.0.0.1:8420/health >/dev/null; then
      return
    fi
    sleep 0.25
  done
  echo "Carivyo backend did not become ready." >&2
  exit 1
}

require_command curl
require_command npm
require_command node
[[ -x "$ROOT/.venv/bin/python" ]] || {
  echo "Python environment is missing. Run 'make install' once from $ROOT." >&2
  exit 1
}
if [[ ! -x "$ROOT/.venv/bin/uvicorn" ]]; then
  if ! "$ROOT/.venv/bin/python" -m pip --version >/dev/null 2>&1; then
    echo "Repairing the local Python environment..."
    "$ROOT/.venv/bin/python" -m ensurepip --upgrade
  fi
  echo "Installing backend dependencies..."
  "$ROOT/.venv/bin/python" -m pip install -e "$ROOT/backend[dev]"
fi
if [[ ! -d "$ROOT/frontend/node_modules" ]]; then
  echo "Installing frontend dependencies..."
  npm --prefix "$ROOT/frontend" ci
fi

CODEX_BIN="$(resolve_codex)"
export PATH="$(dirname "$CODEX_BIN"):$PATH"
export CARIVYO_CODEX_MODEL="gpt-5.6-terra"
export CARIVYO_FULLY_LOCAL_MODE="false"

if ! "$CODEX_BIN" login status 2>&1 | grep -qi "logged in"; then
  echo "Sign in to Codex once to use GPT-5.6 Terra."
  "$CODEX_BIN" login
fi

if ! "$CODEX_BIN" login status 2>&1 | grep -qi "logged in"; then
  echo "Codex login did not complete; Carivyo was not started." >&2
  exit 1
fi

export CARIVYO_BOOTSTRAP_TOKEN="$("$ROOT/.venv/bin/python" -c 'import secrets; print(secrets.token_urlsafe(32))')"
export CARIVYO_NO_OPEN=1

cat <<'LINKS'

Carivyo local demo is starting with Codex CLI + GPT-5.6 Terra.

  Web app:       http://127.0.0.1:5173/
  REST API:      http://127.0.0.1:8420/api
  API docs:      http://127.0.0.1:8420/api/docs
  Health:        http://127.0.0.1:8420/health
  AI runtime:    Codex CLI / gpt-5.6-terra
  Local option:  Ollama remains available in Profile > AI runtime

Press Ctrl+C to stop both services.

LINKS

trap cleanup EXIT INT TERM
"$ROOT/scripts/dev.sh" &
DEV_PID=$!

wait_for_backend
SESSION_TOKEN="$(curl --fail --silent --max-time 5 \
  -H "X-Carivyo-Bootstrap: $CARIVYO_BOOTSTRAP_TOKEN" \
  http://127.0.0.1:8420/api/session \
  | "$ROOT/.venv/bin/python" -c 'import json, sys; print(json.load(sys.stdin)["token"])')"

curl --fail --silent --max-time 10 \
  -X PATCH http://127.0.0.1:8420/api/runtime/settings \
  -H "Content-Type: application/json" \
  -H "X-Carivyo-Session: $SESSION_TOKEN" \
  --data '{"provider":"codex","model":"gpt-5.6-terra","reasoning_effort":"low","fully_local":false}' \
  >/dev/null

if command -v open >/dev/null 2>&1; then
  open "http://127.0.0.1:5173/"
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "http://127.0.0.1:5173/" >/dev/null 2>&1
fi

wait "$DEV_PID"