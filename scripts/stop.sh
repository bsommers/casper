#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_FILE="${CASPER_PID_FILE:-$ROOT/target/casper.pid}"

if [[ ! -f "$PID_FILE" ]]; then
  echo "Casper server is not running (no PID file at $PID_FILE)."
  exit 0
fi

PID="$(tr -d '[:space:]' < "$PID_FILE" || true)"
if [[ -z "$PID" || ! "$PID" =~ ^[0-9]+$ ]]; then
  rm -f "$PID_FILE"
  echo "Removed invalid PID file $PID_FILE."
  exit 0
fi

if ! kill -0 "$PID" 2>/dev/null; then
  rm -f "$PID_FILE"
  echo "Removed stale PID file for exited PID $PID."
  exit 0
fi

CMDLINE=""
if [[ -r "/proc/$PID/cmdline" ]]; then
  CMDLINE="$(tr '\0' ' ' < "/proc/$PID/cmdline" 2>/dev/null || true)"
else
  CMDLINE="$(ps -p "$PID" -o args= 2>/dev/null || true)"
fi

if [[ "$CMDLINE" != *casper* || "$CMDLINE" != *serve* ]]; then
  echo "Error: Refusing to stop PID $PID; process is not a Casper server ($CMDLINE)" >&2
  exit 1
fi

kill -TERM "$PID"
for _ in $(seq 1 50); do
  if ! kill -0 "$PID" 2>/dev/null; then
    rm -f "$PID_FILE"
    echo "Stopped Casper server (PID $PID)."
    exit 0
  fi
  sleep 0.1
done

echo "Error: Casper server (PID $PID) did not exit after SIGTERM" >&2
exit 1
