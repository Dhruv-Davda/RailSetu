#!/usr/bin/env bash
# RailSetu — one-command dev launcher. Starts the FastAPI backend (:8000) and the
# Vite frontend (:5173). Ctrl-C stops both.
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"

echo "▶ Backend  → http://127.0.0.1:8000  (docs at /docs)"
cd "$ROOT/backend"
[ -d .venv ] || python3 -m venv .venv
./.venv/bin/pip install -q -r requirements.txt   # idempotent; picks up new deps
[ -f .env ] || cp .env.example .env              # first-run config from template
./.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 &
BACK=$!

echo "▶ Frontend → http://localhost:5173"
cd "$ROOT/frontend"
[ -d node_modules ] || npm install
npm run dev &
FRONT=$!

trap "echo; echo 'stopping…'; kill $BACK $FRONT 2>/dev/null" INT TERM
wait
