#!/bin/bash
# Stop all Recipe Generator services
# Usage: ./stop_all.sh [--keep-ollama]

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
KEEP_OLLAMA=false

# Parse arguments
if [ "$1" = "--keep-ollama" ]; then
    KEEP_OLLAMA=true
fi

echo "🛑 Stopping Recipe Generator servers..."
echo ""

# Stop backend
echo "🔧 Stopping Backend..."
if pkill -f "uvicorn app.main"; then
    echo "   ✅ Backend stopped"
    [ -f "$PROJECT_ROOT/backend/backend.pid" ] && rm "$PROJECT_ROOT/backend/backend.pid"
else
    echo "   ℹ️  Backend not running"
fi

# Stop frontend
echo "📱 Stopping Frontend..."
if pkill -f "expo start"; then
    echo "   ✅ Frontend stopped"
    [ -f "$PROJECT_ROOT/frontend/frontend.pid" ] && rm "$PROJECT_ROOT/frontend/frontend.pid"
else
    echo "   ℹ️  Frontend not running"
fi

# Stop Ollama (optional)
if [ "$KEEP_OLLAMA" = false ]; then
    echo "🤖 Stopping Ollama..."
    if sudo systemctl is-active --quiet ollama; then
        sudo systemctl stop ollama
        echo "   ✅ Ollama stopped (frees ~6GB RAM)"
    else
        echo "   ℹ️  Ollama not running"
    fi
else
    echo "🤖 Keeping Ollama running (use without --keep-ollama to stop)"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✨ Cleanup complete!"
echo ""
echo "To restart: ./start_all.sh"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
