#!/usr/bin/env bash
# Schedule collect_divvy_gbfs.py --once on Linux (systemd user timer or cron).
# Linux counterpart of install_divvy_collector.ps1: one smoke poll must succeed
# before scheduling; no sudo, passwords, linger or power settings are changed.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: install_divvy_collector.sh --data-root DIR [options]
       install_divvy_collector.sh --uninstall [--mode systemd|cron]

  --data-root DIR         Raw data root, outside Git (e.g. ~/BikeFlowAI-data/divvy)
  --python PATH           Interpreter (default: python3 on PATH)
  --interval-minutes N    1-5, default 2 (same cadence as the retired Windows task)
  --stop-at ISO_UTC       Default 2026-12-13T07:59:00+00:00
  --mode systemd|cron     Default: systemd if a user manager is reachable, else cron
  --dry-run               Print what would be installed; change nothing
  --uninstall             Remove only this collector's timer/cron entry; data kept
EOF
}

NAME='bikeflowai-divvy-gbfs-collector'
CRON_MARK="# $NAME"
PYTHON_EXE=''; DATA_ROOT=''; INTERVAL=2; STOP_AT='2026-12-13T07:59:00+00:00'
MODE=''; DRY_RUN=0; UNINSTALL=0
while [ $# -gt 0 ]; do
  case "$1" in
    --data-root) DATA_ROOT="$2"; shift 2 ;;
    --python) PYTHON_EXE="$2"; shift 2 ;;
    --interval-minutes) INTERVAL="$2"; shift 2 ;;
    --stop-at) STOP_AT="$2"; shift 2 ;;
    --mode) MODE="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    --uninstall) UNINSTALL=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [ -z "$MODE" ]; then
  if command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1; then MODE=systemd; else MODE=cron; fi
fi
case "$MODE" in systemd|cron) ;; *) echo 'Choose --mode systemd or cron' >&2; exit 2 ;; esac
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

current_cron() { crontab -l 2>/dev/null || true; }
# Other users' cron lines are kept; only lines carrying our marker are replaced.
other_cron() { printf '%s\n' "$1" | grep -vF "$CRON_MARK" | grep -v '^$' || true; }

if [ "$UNINSTALL" -eq 1 ]; then
  if [ "$MODE" = systemd ]; then
    systemctl --user disable --now "$NAME.timer" 2>/dev/null || true
    rm -f "$UNIT_DIR/$NAME.timer" "$UNIT_DIR/$NAME.service"
    systemctl --user daemon-reload
  else
    EXISTING="$(current_cron)"
    other_cron "$EXISTING" | crontab -
  fi
  echo "Removed $MODE schedule for $NAME; collected data was not deleted."
  exit 0
fi

[ -n "$DATA_ROOT" ] || { echo '--data-root is required' >&2; usage >&2; exit 2; }
case "$INTERVAL" in 1|2|3|4|5) ;; *) echo 'Choose a 1-5 minute interval' >&2; exit 2 ;; esac
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COLLECTOR="$SCRIPT_DIR/collect_divvy_gbfs.py"
[ -n "$PYTHON_EXE" ] || PYTHON_EXE="$(command -v python3 || true)"
[ -x "$PYTHON_EXE" ] && [ -f "$COLLECTOR" ] || { echo 'Missing interpreter or collector script' >&2; exit 1; }
PYTHON_EXE="$(cd "$(dirname "$PYTHON_EXE")" && pwd)/$(basename "$PYTHON_EXE")"
mkdir -p "$DATA_ROOT" 2>/dev/null || [ "$DRY_RUN" -eq 1 ]
DATA_ROOT="$(cd "$DATA_ROOT" 2>/dev/null && pwd || echo "$DATA_ROOT")"
LOG="$DATA_ROOT/current_validation/scheduler.log"
if [ "$MODE" = systemd ] && [[ "$LOG" =~ [[:space:]] ]]; then
  echo 'systemd append: log paths cannot contain spaces; choose another --data-root or --mode cron' >&2; exit 2
fi

SERVICE="[Unit]
Description=Capture complete official Divvy GBFS station status (BikeFlowAI)
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
WorkingDirectory=$SCRIPT_DIR
ExecStart=\"$PYTHON_EXE\" \"$COLLECTOR\" --data-root \"$DATA_ROOT\" --once --stop-at \"$STOP_AT\"
TimeoutStartSec=90
StandardOutput=append:$LOG
StandardError=append:$LOG
"
# A oneshot service is never started again while it is still running, so polls
# cannot overlap (the collector's own file lock is a second guard).
TIMER="[Unit]
Description=Every $INTERVAL minutes: BikeFlowAI Divvy GBFS poll

[Timer]
OnCalendar=*:0/$INTERVAL:00
AccuracySec=1s
Persistent=false

[Install]
WantedBy=timers.target
"
q() { printf '%q' "$1"; }
CRON_LINE="*/$INTERVAL * * * * cd $(q "$SCRIPT_DIR") && $(q "$PYTHON_EXE") $(q "$COLLECTOR") --data-root $(q "$DATA_ROOT") --once --stop-at $(q "$STOP_AT") >> $(q "$LOG") 2>&1 $CRON_MARK"

if [ "$DRY_RUN" -eq 1 ]; then
  if [ "$MODE" = systemd ]; then
    printf '%s\n%s\n%s\n%s\n' "== $UNIT_DIR/$NAME.service" "$SERVICE" "== $UNIT_DIR/$NAME.timer" "$TIMER"
  else
    printf '%s\n' "== crontab entry" "$CRON_LINE"
  fi
  exit 0
fi

# Smoke poll first, like startCollector in the Apps Script version.
SMOKE="$("$PYTHON_EXE" "$COLLECTOR" --data-root "$DATA_ROOT" --once --stop-at "$STOP_AT")"
echo "$SMOKE"
STATUS="$(printf '%s' "$SMOKE" | "$PYTHON_EXE" -c 'import json,sys; print(json.loads(sys.stdin.read().strip().splitlines()[-1])["status"])')"
[ "$STATUS" = ok ] || { echo "Smoke poll status is '$STATUS'; nothing was scheduled." >&2; exit 1; }

if [ "$MODE" = systemd ]; then
  mkdir -p "$UNIT_DIR"
  printf '%s' "$SERVICE" > "$UNIT_DIR/$NAME.service"
  printf '%s' "$TIMER" > "$UNIT_DIR/$NAME.timer"
  systemctl --user daemon-reload
  systemctl --user enable --now "$NAME.timer"
  systemctl --user list-timers "$NAME.timer" --no-pager
  echo "Runs while this user's systemd manager is active. To keep it running after logout, run once yourself: loginctl enable-linger $USER"
else
  command -v crontab >/dev/null 2>&1 || { echo 'crontab not found; install cron or use --mode systemd' >&2; exit 1; }
  EXISTING="$(current_cron)"
  { other_cron "$EXISTING"; echo "$CRON_LINE"; } | crontab -
  current_cron | grep -F "$CRON_MARK"
  echo 'Runs while the cron daemon is running and the machine is awake/online.'
fi
echo "Log: $LOG   Polls: $DATA_ROOT/current_validation/polls.jsonl"
echo 'Collection stops (no-op polls) after the --stop-at time. Do not run parallel collectors into the same data root by accident.'
