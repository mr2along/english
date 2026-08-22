#!/usr/bin/env bash
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$ROOT/transcript-backend"

if [ -f "$BACKEND/package.json" ]; then
  cd "$BACKEND"
  if [ ! -d node_modules ]; then
    npm install --omit=dev
  fi
  node server.mjs > /tmp/transcript-backend.log 2>&1 &
  BACKEND_PID=$!
  trap 'kill $BACKEND_PID 2>/dev/null || true' EXIT
  cd "$ROOT"
fi

export TRANSCRIPT_BACKEND_URL="${TRANSCRIPT_BACKEND_URL:-http://127.0.0.1:8765}"
exec python app.py
