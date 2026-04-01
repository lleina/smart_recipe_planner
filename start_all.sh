#!/bin/bash
# Start all Recipe Generator services
# Usage:
#   ./start_all.sh          # native Linux / macOS (no tunnel)
#   ./start_all.sh --wsl2   # WSL2: also starts cloudflared API tunnel + expo --tunnel

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"

# Parse --wsl2 flag
WSL2=false
for arg in "$@"; do
    [ "$arg" = "--wsl2" ] && WSL2=true
done

echo "🚀 Starting Recipe Generator servers... (WSL2 mode: $WSL2)"
echo ""

# 1. Start Ollama and models
echo "📦 Step 1: Starting Ollama + AI Models..."
if ! bash backend/scripts/start_models.sh; then
    echo "❌ Failed to start Ollama. Please check the logs."
    exit 1
fi
echo ""

# 2. Start backend
echo "🔧 Step 2: Starting Backend (FastAPI)..."
if [ ! -d "backend/venv" ]; then
    echo "❌ Virtual environment not found. Run setup first:"
    echo "   cd backend && python3 -m venv venv && venv/bin/pip install -r requirements.txt"
    exit 1
fi

if lsof -Pi :8000 -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo "⚠️  Backend already running on port 8000"
else
    echo "   Starting on http://0.0.0.0:8000"
    cd backend
    venv/bin/python -m uvicorn app.main:app --port 8000 --host 0.0.0.0 --reload &
    BACKEND_PID=$!
    echo $BACKEND_PID > "$PROJECT_ROOT/backend/backend.pid"
    cd "$PROJECT_ROOT"

    for i in $(seq 1 10); do
        sleep 1
        if curl -s http://localhost:8000/api/health > /dev/null 2>&1; then
            echo "   ✅ Backend healthy (PID: $BACKEND_PID)"
            break
        fi
    done
    if ! curl -s http://localhost:8000/api/health > /dev/null 2>&1; then
        echo "   ⚠️  Backend started but health check failed (PID: $BACKEND_PID)"
    fi
fi
echo ""

# 3. API tunnel (WSL2 only)
if [ "$WSL2" = true ]; then
    echo "🌐 Step 3: Starting API tunnel (cloudflared)..."
    if pgrep -f "cloudflared.*tunnel" > /dev/null 2>&1; then
        echo "⚠️  API tunnel already running"
    else
        bash backend/scripts/start_api_tunnel.sh &
        echo "   ✅ API tunnel starting in background (updates frontend/.env when ready)"
    fi
    echo ""
fi

# 4. Start frontend
echo "📱 Step 4: Starting Frontend (Expo)..."
if ps aux | grep -i "expo start" | grep -v grep > /dev/null 2>&1; then
    echo "⚠️  Frontend already running"
else
    cd frontend
    export NVM_DIR="$HOME/.nvm"
    # shellcheck disable=SC1091
    [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh" && nvm use 22
    if [ "$WSL2" = true ]; then
        npx expo start --tunnel &
    else
        npx expo start &
    fi
    FRONTEND_PID=$!
    echo $FRONTEND_PID > "$PROJECT_ROOT/frontend/frontend.pid"
    echo "   ✅ Frontend started (PID: $FRONTEND_PID)"
    echo "   📲 Scan the QR code with Expo Go app"
    cd "$PROJECT_ROOT"
fi
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✨ All servers started!"
echo ""
echo "Backend:  http://localhost:8000"
if [ "$WSL2" = true ]; then
    echo "Tunnel:   see frontend/.env for public URL"
fi
echo "Frontend: Check QR code above"
echo "Ollama:   http://localhost:11434"
echo ""
echo "To stop all servers: ./stop_all.sh"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
