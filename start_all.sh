#!/bin/bash
# Start all Recipe Generator services
# Usage: ./start_all.sh

set -e

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"

echo "🚀 Starting Recipe Generator servers..."
echo ""

# 1. Start Ollama and models
echo "📦 Step 1: Starting Ollama + AI Models..."
bash backend/scripts/start_models.sh
if [ $? -ne 0 ]; then
    echo "❌ Failed to start Ollama. Please check the logs."
    exit 1
fi
echo ""

# 2. Start backend
echo "🔧 Step 2: Starting Backend (FastAPI)..."
cd backend
if [ ! -d "venv" ]; then
    echo "❌ Virtual environment not found. Run setup first:"
    echo "   cd backend && python3 -m venv venv && venv/bin/pip install -r requirements.txt"
    exit 1
fi

# Check if backend already running
if lsof -Pi :8000 -sTCP:LISTEN -t >/dev/null ; then
    echo "⚠️  Backend already running on port 8000"
else
    echo "   Starting on http://0.0.0.0:8000"
    venv/bin/python -m uvicorn app.main:app --reload --port 8000 --host 0.0.0.0 &
    BACKEND_PID=$!
    echo $BACKEND_PID > backend.pid
    
    # Wait for backend to start
    sleep 3
    if curl -s http://localhost:8000/api/health > /dev/null; then
        echo "   ✅ Backend healthy (PID: $BACKEND_PID)"
    else
        echo "   ⚠️  Backend started but health check failed"
    fi
fi
cd ..
echo ""

# 3. Start frontend
echo "📱 Step 3: Starting Frontend (Expo)..."
cd frontend

# Check if frontend already running
if ps aux | grep -i "expo start" | grep -v grep > /dev/null; then
    echo "⚠️  Frontend already running"
else
    echo "   Starting with tunnel mode for WSL2..."
    npx expo start --tunnel &
    FRONTEND_PID=$!
    echo $FRONTEND_PID > frontend.pid
    echo "   ✅ Frontend started (PID: $FRONTEND_PID)"
    echo "   📲 Scan the QR code with Expo Go app"
fi
cd ..
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✨ All servers started!"
echo ""
echo "Backend:  http://localhost:8000"
echo "Frontend: Check QR code above"
echo "Ollama:   http://localhost:11434"
echo ""
echo "To stop all servers: pkill -f 'uvicorn app.main' && pkill -f 'expo start'"
echo "Or see SERVER_MANAGEMENT.md for detailed commands"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
