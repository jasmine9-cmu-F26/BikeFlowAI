#!/usr/bin/env bash
# macOS / Linux equivalent of scripts/stop_demo.ps1.
set -euo pipefail
PID_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/.local/demo-processes"
if [ ! -f "$PID_FILE" ]; then echo "No managed demo processes."; exit 0; fi
stopped=""
while read -r pid recorded; do
  [ -n "$pid" ] || continue
  current="$(ps -p "$pid" -o command= 2>/dev/null || true)"
  # Only stop the process we started (same PID and same command line).
  if [ -n "$current" ] && [ "$current" = "$recorded" ]; then
    kill "$pid" 2>/dev/null || true
    stopped="$stopped $pid"
  fi
done <"$PID_FILE"
# Wait up to 10 s for graceful shutdown so ports are free when this returns.
for _ in $(seq 1 20); do
  alive=0
  for pid in $stopped; do kill -0 "$pid" 2>/dev/null && alive=1; done
  [ "$alive" = 0 ] && break
  sleep 0.5
done
rm -f "$PID_FILE"
echo "Stopped managed BikeFlow demo processes."
