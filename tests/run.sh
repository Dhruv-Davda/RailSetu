#!/usr/bin/env bash
#
# Run every suite, from a clean state, and print one total.
#
#   ./tests/run.sh          everything
#   ./tests/run.sh api      the Python suites only (no browser needed)
#   ./tests/run.sh ui       the browser suites only
#
# The API suites run in-process against the app; each provisions its own policy
# and account store, so they neither need a server nor disturb one. The UI
# suites need a browser and a running stack, so this script starts the backend
# and the dev server itself, on ports of its own, and stops them at the end.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WHICH="${1:-all}"
PY="$ROOT/backend/.venv/bin/python"
API_PORT="${RAILSETU_TEST_API_PORT:-8111}"
WEB_PORT="${RAILSETU_TEST_WEB_PORT:-5111}"

[ -x "$PY" ] || PY="$(command -v python3)"

pass=0; fail=0; failed_suites=()
bar() { printf '\n\033[1m%s\033[0m\n' "── $* ────────────────────────────────────────────" ; }

tally() {   # tally <name> <output>
  local name="$1" out="$2"
  local line p f
  line="$(printf '%s\n' "$out" | grep -Eio '[0-9]+(/[0-9]+)? passed, [0-9]+ failed' | tail -1)"
  if [ -z "$line" ]; then
    printf '  \033[31m%-26s no result — the suite did not finish\033[0m\n' "$name"
    printf '%s\n' "$out" | grep -vE '^\s*$' | tail -8 | sed 's/^/      /'
    failed_suites+=("$name (crashed)"); fail=$((fail + 1)); return
  fi
  p="$(printf '%s' "$line" | grep -Eo '^[0-9]+')"
  f="$(printf '%s' "$line" | grep -Eo '[0-9]+ failed' | grep -Eo '^[0-9]+')"
  pass=$((pass + p)); fail=$((fail + f))
  if [ "$f" -gt 0 ]; then
    printf '  \033[31m%-26s %3d passed, %d FAILED\033[0m\n' "$name" "$p" "$f"
    failed_suites+=("$name")
    printf '%s\n' "$out" | grep -E '^\s+FAIL' | sed 's/^/      /'
  else
    printf '  \033[32m%-26s %3d passed\033[0m\n' "$name" "$p"
  fi
}

# ───────────────────────────────────────────────────────────── API suites
if [ "$WHICH" = all ] || [ "$WHICH" = api ]; then
  bar "API — in-process, no server, no network"
  for f in "$ROOT"/tests/api/test_*.py; do
    name="$(basename "$f" .py)"
    # test_defect drives the ML models over HTTP, so it needs the server below.
    [ "$name" = test_defect ] && continue
    tally "$name" "$(cd "$ROOT/tests/api" && "$PY" "$f" 2>&1)"
  done
fi

# ───────────────────────────────────────────────── stack for the HTTP/UI suites
need_stack=false
[ "$WHICH" = all ] || [ "$WHICH" = ui ] && need_stack=true

API_PID=""; WEB_PID=""

start_api() {   # start_api <store-name>
  local work="$ROOT/tests/.work/stack/$1"
  # Stop the previous backend and WAIT for the port to be free. `wait` returns
  # immediately for a job started in a subshell, so without this the old server
  # is still serving when the store directory below is deleted out from under it
  # — the register comes back empty and every editor assertion fails for a reason
  # that has nothing to do with the product.
  if [ -n "$API_PID" ]; then
    kill "$API_PID" 2>/dev/null
    wait "$API_PID" 2>/dev/null
    for _ in $(seq 40); do
      curl -sf -m 1 "http://127.0.0.1:$API_PORT/api/health" >/dev/null || break
      sleep 0.25
    done
  fi
  rm -rf "$work"; mkdir -p "$work/policy" "$work/accounts"
  ( cd "$ROOT/backend" && \
    RAILSETU_POLICY_STORE=local \
    RAILSETU_ACCOUNTS_STORE=local \
    RAILSETU_POLICY_LOCAL_ROOT="$work/policy" \
    RAILSETU_ACCOUNTS_LOCAL_ROOT="$work/accounts" \
    RAILSETU_M3_ARTIFACTS_DIR="$ROOT/railsetu-m3/artifacts" \
    exec "$PY" -m uvicorn app.main:app --port "$API_PORT" >"$ROOT/tests/.work/stack/api.log" 2>&1 ) &
  API_PID=$!
  for _ in $(seq 60); do
    curl -sf "http://127.0.0.1:$API_PORT/api/health" >/dev/null && return 0
    sleep 1
  done
  echo "  the backend did not come up — see tests/.work/stack/api.log"; return 1
}

if $need_stack; then
  bar "Starting the stack on :$API_PORT (api) and :$WEB_PORT (web)"
  mkdir -p "$ROOT/tests/.work/stack"

  ( cd "$ROOT/frontend" && \
    RAILSETU_API_PORT="$API_PORT" \
    exec npx vite --host 127.0.0.1 --port "$WEB_PORT" --strictPort \
      >"$ROOT/tests/.work/stack/web.log" 2>&1 ) &
  WEB_PID=$!

  cleanup() { kill "$API_PID" "$WEB_PID" 2>/dev/null; wait 2>/dev/null; }
  trap cleanup EXIT

  start_api boot || exit 1
  for _ in $(seq 60); do
    curl -sf "http://127.0.0.1:$WEB_PORT/" >/dev/null && break
    sleep 1
  done
  if ! curl -sf "http://127.0.0.1:$WEB_PORT/" >/dev/null; then
    echo "  the dev server did not come up — see tests/.work/stack/web.log"; exit 1
  fi
  echo "  up"
fi

# ───────────────────────────────────────────────────── the ML suite (over HTTP)
if [ "$WHICH" = all ] || [ "$WHICH" = api ]; then
  if $need_stack; then
    bar "API — over HTTP (loads the two networks)"
    tally "test_defect" \
      "$(cd "$ROOT/tests/api" && RAILSETU_BASE="http://127.0.0.1:$API_PORT" "$PY" test_defect.py 2>&1)"
  fi
fi

# ────────────────────────────────────────────────────────────── UI suites
if [ "$WHICH" = all ] || [ "$WHICH" = ui ]; then
  bar "UI — headless Chromium against the running stack"
  # Each browser suite gets a backend with an EMPTY register. They activate,
  # revert and add documents; run them against a shared store and the third one
  # is asserting against whatever the first two left behind.
  for f in "$ROOT"/tests/ui/*.mjs; do
    name="$(basename "$f" .mjs)"
    start_api "ui-$name" || { tally "$name" ""; continue; }
    tally "$name" "$(RAILSETU_BASE="http://127.0.0.1:$WEB_PORT" node "$f" 2>&1)"
  done
fi

# ───────────────────────────────────────────────────────────────── total
printf '\n%s\n' "══════════════════════════════════════════════════════════"
if [ "$fail" -eq 0 ]; then
  printf '\033[32m  %d checks passed, 0 failed\033[0m\n' "$pass"
else
  printf '\033[31m  %d passed, %d FAILED\033[0m\n' "$pass" "$fail"
  printf '  in: %s\n' "${failed_suites[*]}"
fi
exit $([ "$fail" -eq 0 ] && echo 0 || echo 1)
