#!/usr/bin/env bash
# =============================================================================
# start_models.sh — Start Ollama + ensure required models are ready
#
# Usage:
#   bash backend/scripts/start_models.sh          # from repo root
#   bash scripts/start_models.sh                  # from backend/
#
# What it does:
#   1. Checks if Ollama is installed (tells you to run setup_ollama.sh if not).
#   2. Starts the Ollama server if it's not already running.
#   3. Pulls qwen3-vl:4b (VLM) and qwen3:4b (LLM) if missing.
#   4. Warms up both models with a tiny prompt so first real request is fast.
#   5. Prints status and a ready message.
# =============================================================================

set -euo pipefail

info()  { echo -e "\033[0;34m[INFO]\033[0m  $*"; }
ok()    { echo -e "\033[0;32m[OK]\033[0m    $*"; }
warn()  { echo -e "\033[0;33m[WARN]\033[0m  $*"; }
die()   { echo -e "\033[0;31m[ERROR]\033[0m $*" >&2; exit 1; }

OLLAMA_HOST="${OLLAMA_HOST:-http://127.0.0.1:11434}"
VLM_MODEL="${VLM_MODEL:-qwen3-vl:4b}"
LLM_MODEL="${LLM_MODEL:-qwen3:4b}"

# ---- 1. Check Ollama installed ----
if ! command -v ollama &>/dev/null; then
    die "Ollama is not installed. Run:  bash backend/scripts/setup_ollama.sh"
fi
ok "Ollama binary found: $(command -v ollama)"

# ---- 2. Start server if not running ----
if curl -sf "${OLLAMA_HOST}/api/tags" &>/dev/null; then
    ok "Ollama server already running at ${OLLAMA_HOST}"
else
    info "Starting Ollama server..."
    ollama serve &>/tmp/ollama-serve.log &
    OLLAMA_PID=$!

    for i in $(seq 1 30); do
        if curl -sf "${OLLAMA_HOST}/api/tags" &>/dev/null; then
            ok "Ollama server started (PID ${OLLAMA_PID})"
            break
        fi
        sleep 0.5
    done

    if ! curl -sf "${OLLAMA_HOST}/api/tags" &>/dev/null; then
        die "Ollama server failed to start. Check /tmp/ollama-serve.log"
    fi
fi

# ---- 3. Pull models if missing ----
pull_if_missing() {
    local model="$1"
    if ollama list 2>/dev/null | grep -q "${model}"; then
        ok "Model ready: ${model}"
    else
        info "Pulling ${model} (this may take a few minutes on first run)..."
        ollama pull "${model}"
        ok "Pulled: ${model}"
    fi
}

pull_if_missing "${VLM_MODEL}"
pull_if_missing "${LLM_MODEL}"

# ---- 4. Warm up models (optional, makes first request faster) ----
info "Warming up ${LLM_MODEL}..."
curl -sf "${OLLAMA_HOST}/api/generate" \
    -d "{\"model\":\"${LLM_MODEL}\",\"prompt\":\"hi\",\"stream\":false}" \
    -o /dev/null 2>/dev/null && ok "Warm: ${LLM_MODEL}" || warn "Warm-up skipped for ${LLM_MODEL}"

info "Warming up ${VLM_MODEL}..."
curl -sf "${OLLAMA_HOST}/api/generate" \
    -d "{\"model\":\"${VLM_MODEL}\",\"prompt\":\"hi\",\"stream\":false}" \
    -o /dev/null 2>/dev/null && ok "Warm: ${VLM_MODEL}" || warn "Warm-up skipped for ${VLM_MODEL}"

# ---- 5. Done ----
echo ""
ok "Models are ready!"
echo ""
echo "  VLM : ${VLM_MODEL}  (ingredient recognition)"
echo "  LLM : ${LLM_MODEL}  (recipe ideation + ranking)"
echo "  API : ${OLLAMA_HOST}/v1  (OpenAI-compatible)"
echo ""
echo "  Start the backend:"
echo "    cd backend && source venv/bin/activate"
echo "    uvicorn app.main:app --reload --port 8000"
echo ""
echo "  To stop models:  bash backend/scripts/stop_models.sh"
