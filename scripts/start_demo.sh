#!/usr/bin/env bash
# macOS / Linux equivalent of scripts/start_demo.ps1.
# Usage: ./scripts/start_demo.sh [--python PATH] [--no-live]
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$PROJECT_ROOT/.venv/bin/python"
NO_LIVE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --python) PYTHON="$2"; shift 2 ;;
    --no-live) NO_LIVE=1; shift ;;
    -h|--help) echo "Usage: $0 [--python PATH] [--no-live]"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

fail() { echo "error: $*" >&2; exit 1; }

[ -x "$PYTHON" ] || fail "Python environment missing at $PYTHON. Run 'make demo-setup' (or create .venv and install backend/requirements-demo.txt); see docs/app_demo.md."
NODE="$(command -v node)" || fail "Node.js 22+ is required on PATH."
VITE="$PROJECT_ROOT/frontend/node_modules/vite/bin/vite.js"
[ -f "$VITE" ] || fail "Frontend dependencies missing. Run 'npm ci' in frontend/ (or 'make demo-setup')."
command -v curl >/dev/null || fail "curl is required for the readiness check."

RUNTIME="$PROJECT_ROOT/.local"
PID_FILE="$RUNTIME/demo-processes"
mkdir -p "$RUNTIME"
if [ -e "$PID_FILE" ]; then
  alive=0; total=0
  while read -r pid recorded; do
    [ -n "$pid" ] || continue
    total=$((total + 1))
    [ "$(ps -p "$pid" -o command= 2>/dev/null || true)" = "$recorded" ] && alive=$((alive + 1))
  done <"$PID_FILE"
  if [ "$total" -gt 0 ] && [ "$alive" = "$total" ]; then
    echo "BikeFlow is already running: http://127.0.0.1:3000"
    echo "To restart: make demo-stop && make demo"
    exit 0
  elif [ "$alive" = 0 ]; then
    rm -f "$PID_FILE"   # stale record from a previous run that already exited
  else
    fail "A previous demo is only partly running. Run ./scripts/stop_demo.sh (make demo-stop) first."
  fi
fi

port_busy() {
  if command -v lsof >/dev/null; then
    lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
  else
    (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null
  fi
}
for port in 8000 3000; do
  if port_busy "$port"; then fail "Port $port is already in use. Stop its owner before starting the demo."; fi
done

[ "$NO_LIVE" = 1 ] && export BIKEFLOW_LIVE=0

cd "$PROJECT_ROOT"
nohup "$PYTHON" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --no-access-log \
  >"$RUNTIME/api.out.log" 2>"$RUNTIME/api.err.log" </dev/null &
API_PID=$!
(cd "$PROJECT_ROOT/frontend" && exec nohup "$NODE" node_modules/vite/bin/vite.js --host 127.0.0.1 --port 3000 --strictPort \
  >"$RUNTIME/web.out.log" 2>"$RUNTIME/web.err.log" </dev/null) &
WEB_PID=$!
record_pids() {
  # PID + command line, so stop_demo.sh never kills an unrelated reused PID.
  {
    echo "$API_PID $(ps -p "$API_PID" -o command= 2>/dev/null)"
    echo "$WEB_PID $(ps -p "$WEB_PID" -o command= 2>/dev/null)"
  } >"$PID_FILE"
}
record_pids

cleanup_failed() {
  kill "$API_PID" "$WEB_PID" 2>/dev/null || true
  rm -f "$PID_FILE"
}

HEALTH=""
for _ in $(seq 1 60); do
  if ! kill -0 "$API_PID" 2>/dev/null || ! kill -0 "$WEB_PID" 2>/dev/null; then
    cleanup_failed; fail "Demo process exited. Inspect .local/*.log."
  fi
  if HEALTH="$(curl -fsS --max-time 2 http://127.0.0.1:8000/health 2>/dev/null)" &&
     curl -fsS --max-time 2 -o /dev/null http://127.0.0.1:3000; then
    break
  fi
  HEALTH=""
  sleep 0.5
done
[ -n "$HEALTH" ] || { cleanup_failed; fail "Demo startup timed out. Inspect .local/*.log."; }

# Re-record now that nohup has exec'd into python/node (the command line changes after exec).
record_pids
echo "BikeFlow is ready: http://127.0.0.1:3000"
"$PYTHON" -c 'import json,sys; h=json.load(sys.stdin); print("Forecast: {} | Data: {} | PPO runtime ready: {}".format(h.get("active_method"), h.get("data_source"), h.get("rl_ready")))' <<<"$HEALTH"
echo "API docs: http://127.0.0.1:8000/docs | Stop: ./scripts/stop_demo.sh"
