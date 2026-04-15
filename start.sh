#!/usr/bin/env bash
# ── Federal Litigation Tracker — Startup Script ─────────────────────
# Usage: ./start.sh
# This script installs dependencies and starts the tracker.

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== Federal Litigation Tracker ==="
echo ""

# Load .env if present
if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a
    source "$SCRIPT_DIR/.env"
    set +a
    echo "[✓] Loaded .env"
else
    echo "[!] No .env file found. Copy .env.example to .env and set your values."
    echo "    Using defaults (no CourtListener token — rate limits apply)."
fi

# Install Python deps if needed
if ! python3 -c "import flask" 2>/dev/null; then
    echo "[~] Installing Python dependencies..."
    pip3 install -q -r "$SCRIPT_DIR/backend/requirements.txt"
    echo "[✓] Dependencies installed"
else
    echo "[✓] Dependencies present"
fi

echo ""
echo "[~] Starting server on port ${PORT:-5000}..."
echo "    Open: http://localhost:${PORT:-5000}"
echo "    Daily sync runs at 06:00 UTC every day."
echo "    Press Ctrl+C to stop."
echo ""

cd "$SCRIPT_DIR/backend"
python3 app.py
