#!/usr/bin/env bash
# Start SyncSpace on all interfaces (LAN-friendly) and print local URLs.
# Usage: ./start.sh   or   bash start.sh
# Optional: SYNCSPACE_PORT=9000 ./start.sh
# Localhost only: SYNCSPACE_HOST=127.0.0.1 ./start.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMPL_ROOT="$SCRIPT_DIR"
SERVER_DIR="$IMPL_ROOT/src/server"
VENV_PY="$IMPL_ROOT/.venv/bin/python"
PORT="${SYNCSPACE_PORT:-8080}"

if [[ ! -x "$VENV_PY" ]]; then
  echo "Missing venv Python at: $VENV_PY" >&2
  echo "Create it from the Implementation folder:" >&2
  echo "  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

print_urls() {
  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  SyncSpace"
  echo ""
  echo "  On this computer:"
  echo "    http://127.0.0.1:${PORT}/"
  echo ""
  echo "  Same Wi‑Fi / LAN (open on phones & other laptops):"
  local any=0
  if [[ "$(uname -s)" == "Darwin" ]]; then
    for iface in en0 en1 en2; do
      local ip
      ip="$(ipconfig getifaddr "$iface" 2>/dev/null || true)"
      if [[ -n "$ip" ]]; then
        echo "    http://${ip}:${PORT}/   (interface ${iface})"
        any=1
      fi
    done
  else
    local ip=""
    if command -v ip >/dev/null 2>&1; then
      ip="$(ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.*src \([^ ]*\).*/\1/p' | head -1 || true)"
    fi
    if [[ -z "$ip" ]] && command -v hostname >/dev/null 2>&1; then
      for cand in $(hostname -I 2>/dev/null || true); do
        [[ "$cand" == 127.* ]] && continue
        ip="$cand"
        break
      done
    fi
    if [[ -n "$ip" ]]; then
      echo "    http://${ip}:${PORT}/"
      any=1
    fi
  fi
  if [[ "$any" -eq 0 ]]; then
    echo "    (could not detect — try: ipconfig getifaddr en0  on macOS)"
    echo "             or: ip -4 route get 1.1.1.1  on Linux)"
  fi
  echo ""
  echo "  Listening on 0.0.0.0:${PORT} — allow TCP ${PORT} in the firewall if needed."
  echo "  Press Ctrl+C to stop."
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo ""
}

export SYNCSPACE_HOST="${SYNCSPACE_HOST:-0.0.0.0}"
export SYNCSPACE_PORT="$PORT"

print_urls
cd "$SERVER_DIR"
exec "$VENV_PY" server.py
