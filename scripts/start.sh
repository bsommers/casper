#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PID_FILE="${CASPER_PID_FILE:-$ROOT/target/casper.pid}"
LOG_FILE="${CASPER_LOG_FILE:-$ROOT/target/casper-server.log}"
AUTHORS_DIR="${CASPER_AUTHORS_DIR:-$ROOT/authors}"
PORT=8731
BACKGROUND=0
OPEN_BROWSER=0
NO_INSTALL=0

usage() {
  cat <<'EOF'
Usage: scripts/start.sh [--background] [--open] [--port N] [--no-install]
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --background)
      BACKGROUND=1
      shift
      ;;
    --open)
      OPEN_BROWSER=1
      shift
      ;;
    --port)
      PORT="${2:-}"
      if [[ -z "$PORT" || ! "$PORT" =~ ^[0-9]+$ ]]; then
        echo "Error: --port requires a numeric port" >&2
        exit 2
      fi
      shift 2
      ;;
    --no-install)
      NO_INSTALL=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

mkdir -p "$(dirname "$PID_FILE")" "$(dirname "$LOG_FILE")"

is_casper_pid() {
  local pid="$1"
  [[ -n "$pid" && "$pid" =~ ^[0-9]+$ ]] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  local cmdline=""
  if [[ -r "/proc/$pid/cmdline" ]]; then
    cmdline="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)"
  else
    cmdline="$(ps -p "$pid" -o args= 2>/dev/null || true)"
  fi
  [[ "$cmdline" == *casper* && "$cmdline" == *serve* ]]
}

# 1. Refuse if live Casper instance is already recorded in PID file; clean stale PID file.
if [[ -f "$PID_FILE" ]]; then
  EXISTING_PID="$(tr -d '[:space:]' < "$PID_FILE" || true)"
  if [[ -n "$EXISTING_PID" ]] && kill -0 "$EXISTING_PID" 2>/dev/null; then
    if is_casper_pid "$EXISTING_PID"; then
      echo "Error: Casper server is already running (PID $EXISTING_PID)" >&2
      exit 1
    fi
    echo "Error: PID file $PID_FILE references live non-Casper process $EXISTING_PID" >&2
    exit 1
  fi
  rm -f "$PID_FILE"
fi

# 2. Ensure .venv exists and casper is importable (unless --no-install).
PYTHON="$ROOT/.venv/bin/python"
CASPER_BIN="$ROOT/.venv/bin/casper"
if [[ ! -x "$PYTHON" ]]; then
  if [[ "$NO_INSTALL" -eq 1 ]]; then
    echo "Error: .venv/bin/python not found and --no-install was specified" >&2
    exit 1
  fi
  if command -v uv >/dev/null 2>&1; then
    uv venv "$ROOT/.venv"
  else
    python3 -m venv "$ROOT/.venv"
  fi
fi

if ! "$PYTHON" -c "import casper.web.server" >/dev/null 2>&1; then
  if [[ "$NO_INSTALL" -eq 1 ]]; then
    echo "Error: casper is not importable in .venv and --no-install was specified" >&2
    exit 1
  fi
  if command -v uv >/dev/null 2>&1; then
    uv pip install --python "$PYTHON" -e "$ROOT"
  else
    "$PYTHON" -m pip install -e "$ROOT"
  fi
fi

# 3. Refuse if requested port is already bound on 127.0.0.1.
if ! "$PYTHON" - "$PORT" <<'PY'
import socket, sys
port = int(sys.argv[1])
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    s.bind(("127.0.0.1", port))
except OSError:
    sys.exit(1)
finally:
    s.close()
PY
then
  echo "Error: Port $PORT on 127.0.0.1 is already in use" >&2
  exit 1
fi

# 4. Warn if authors/ has no .yaml profiles.
shopt -s nullglob
AUTHOR_YAMLS=("$AUTHORS_DIR"/*.yaml)
shopt -u nullglob
if [[ ${#AUTHOR_YAMLS[@]} -eq 0 ]]; then
  echo "Warning: No author profiles (*.yaml) found in $AUTHORS_DIR" >&2
fi

SERVE_CMD=("$PYTHON" -m casper.cli serve --host 127.0.0.1 --port "$PORT" --authors-dir "$AUTHORS_DIR")
if [[ -x "$CASPER_BIN" ]]; then
  SERVE_CMD=("$CASPER_BIN" serve --host 127.0.0.1 --port "$PORT" --authors-dir "$AUTHORS_DIR")
fi

open_url() {
  local url="http://127.0.0.1:$PORT/"
  if [[ "$OPEN_BROWSER" -eq 1 ]]; then
    if command -v xdg-open >/dev/null 2>&1; then
      xdg-open "$url" >/dev/null 2>&1 &
    elif command -v open >/dev/null 2>&1; then
      open "$url" >/dev/null 2>&1 &
    fi
  fi
}

if [[ "$BACKGROUND" -eq 1 ]]; then
  nohup "${SERVE_CMD[@]}" >>"$LOG_FILE" 2>&1 </dev/null &
  SERVER_PID=$!
  echo "$SERVER_PID" > "$PID_FILE"

  # Wait up to 10s for localhost server to respond.
  READY=0
  for _ in $(seq 1 50); do
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
      rm -f "$PID_FILE"
      echo "Error: Casper server exited unexpectedly; check $LOG_FILE" >&2
      exit 1
    fi
    if "$PYTHON" - "$PORT" <<'PY' >/dev/null 2>&1
import http.client, sys
port = int(sys.argv[1])
conn = http.client.HTTPConnection("127.0.0.1", port, timeout=1.0)
conn.request("GET", "/api/options", headers={"Host": f"127.0.0.1:{port}"})
resp = conn.getresponse()
sys.exit(0 if resp.status == 200 else 1)
PY
    then
      READY=1
      break
    fi
    sleep 0.2
  done

  if [[ "$READY" -ne 1 ]]; then
    kill -TERM "$SERVER_PID" 2>/dev/null || true
    rm -f "$PID_FILE"
    echo "Error: Casper server did not become ready on http://127.0.0.1:$PORT/" >&2
    exit 1
  fi

  open_url
  echo "Casper server started on http://127.0.0.1:$PORT/ (PID $SERVER_PID)"
  exit 0
fi

cleanup() {
  rm -f "$PID_FILE"
}
trap cleanup EXIT INT TERM
echo "$$" > "$PID_FILE"
open_url
exec "${SERVE_CMD[@]}"
