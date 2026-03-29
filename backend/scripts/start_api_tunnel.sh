#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Starts a Cloudflare tunnel for the backend API (port 8000) so that phones
# running Expo Go can reach the FastAPI server from WSL2.
#
# Why cloudflared instead of ngrok?
#   - Free, no auth token required for quick tunnels
#   - Can run alongside Expo's ngrok tunnel (no single-session limit)
#
# Usage:
#   bash backend/scripts/start_api_tunnel.sh          # default port 8000
#   bash backend/scripts/start_api_tunnel.sh 8000      # explicit port
#
# The script:
#   1. Downloads cloudflared if not found
#   2. Starts a tunnel on the specified port
#   3. Extracts the public URL from logs
#   4. Updates frontend/.env with the public URL
#   5. Keeps running until Ctrl+C
# ---------------------------------------------------------------------------

set -euo pipefail

PORT=${1:-8000}
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FRONTEND_ENV="$SCRIPT_DIR/../../frontend/.env"
CF_BIN="/tmp/cloudflared"
CF_LOG="/tmp/cloudflared_api.log"

# Download cloudflared if not present
if [ ! -x "$CF_BIN" ]; then
  echo "Downloading cloudflared..."
  curl -sL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
    -o "$CF_BIN" && chmod +x "$CF_BIN"
  echo "cloudflared downloaded to $CF_BIN"
fi

# Kill any existing cloudflared tunnel
pkill -f "cloudflared.*tunnel" 2>/dev/null || true
sleep 1

echo "Starting cloudflared tunnel on port $PORT..."
"$CF_BIN" tunnel --url "http://localhost:$PORT" > "$CF_LOG" 2>&1 &
CF_PID=$!

# Wait for the tunnel URL (cloudflared logs it to stderr)
URL=""
for i in $(seq 1 30); do
  sleep 1
  URL=$(grep -oP 'https://[a-z0-9-]+\.trycloudflare\.com' "$CF_LOG" 2>/dev/null | head -1 || true)
  if [ -n "$URL" ]; then
    break
  fi
done

if [ -z "$URL" ]; then
  echo "ERROR: Could not get cloudflared tunnel URL after 30 seconds."
  echo "Check $CF_LOG for details."
  kill "$CF_PID" 2>/dev/null
  exit 1
fi

API_URL="${URL}/api"
echo ""
echo "================================================"
echo "  Backend API tunnel active!"
echo "  Public URL:  $API_URL"
echo "  PID:         $CF_PID"
echo "================================================"
echo ""

# Update frontend .env
if [ -f "$FRONTEND_ENV" ]; then
  if grep -q "EXPO_PUBLIC_API_BASE_URL" "$FRONTEND_ENV"; then
    sed -i "s|EXPO_PUBLIC_API_BASE_URL=.*|EXPO_PUBLIC_API_BASE_URL=$API_URL|" "$FRONTEND_ENV"
  else
    echo "EXPO_PUBLIC_API_BASE_URL=$API_URL" >> "$FRONTEND_ENV"
  fi
  echo "Updated $FRONTEND_ENV"
  echo "  EXPO_PUBLIC_API_BASE_URL=$API_URL"
  echo ""
  echo ">>> Restart Expo to pick up the new URL <<<"
else
  echo "WARNING: $FRONTEND_ENV not found. Set manually:"
  echo "  EXPO_PUBLIC_API_BASE_URL=$API_URL"
fi

echo ""
echo "Press Ctrl+C to stop the tunnel."

# Trap Ctrl+C to clean up
trap "echo ''; echo 'Stopping tunnel...'; kill $CF_PID 2>/dev/null; exit 0" INT TERM
wait "$CF_PID"
