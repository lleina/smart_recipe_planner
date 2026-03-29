#!/usr/bin/env bash
# =============================================================================
# setup_ollama.sh — Install Ollama on Ubuntu/WSL and pull project models
#
# Usage (from repo root or backend/):
#   bash backend/scripts/setup_ollama.sh
#
# What this script does:
#   1. Installs Ollama (curl-based installer) if not already present.
#   2. Starts the Ollama server in the background.
#   3. Pulls qwen2-vl:7b  (VLM — ingredient recognition).
#   4. Pulls qwen2.5:3b   (LLM — recipe ideation + re-ranking).
#   5. Copies .env.example → .env if .env does not yet exist.
#
# Hardware notes (Ubuntu/WSL2):
#   - qwen3-vl:4b  requires ~3 GB VRAM or ~5 GB RAM for CPU inference.
#   - qwen3:4b     requires ~3 GB VRAM or ~5 GB RAM for CPU inference.
#   - Both models run on CPU if no CUDA GPU is available (slower but functional).
#   - If you have < 8 GB total RAM, swap to 2b variants.
#
# Model swap guide (edit .env after running this script):
#   More VRAM / better quality : VLM_MODEL=qwen3-vl:8b   LLM_MODEL=qwen3:8b
#   Default (balanced)         : VLM_MODEL=qwen3-vl:4b   LLM_MODEL=qwen3:4b
#   CPU-only / low RAM         : VLM_MODEL=qwen3-vl:2b   LLM_MODEL=qwen3:1.7b
# =============================================================================

set -euo pipefail

# --------------------------------------------------------------------------- #
# Helpers                                                                       #
# --------------------------------------------------------------------------- #
info()  { echo -e "\033[0;34m[INFO]\033[0m  $*"; }
ok()    { echo -e "\033[0;32m[OK]\033[0m    $*"; }
warn()  { echo -e "\033[0;33m[WARN]\033[0m  $*"; }
die()   { echo -e "\033[0;31m[ERROR]\033[0m $*" >&2; exit 1; }

# --------------------------------------------------------------------------- #
# 1. Install Ollama                                                              #
# --------------------------------------------------------------------------- #
if ! command -v ollama &>/dev/null; then
    info "Installing Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh
    ok "Ollama installed."
else
    ok "Ollama already installed: $(ollama --version 2>/dev/null || echo 'unknown version')"
fi

# --------------------------------------------------------------------------- #
# 2. Start Ollama server (background)                                           #
# --------------------------------------------------------------------------- #
OLLAMA_HOST="${OLLAMA_HOST:-http://127.0.0.1:11434}"

if curl -sf "${OLLAMA_HOST}/api/tags" &>/dev/null; then
    ok "Ollama server is already running at ${OLLAMA_HOST}."
else
    info "Starting Ollama server..."
    ollama serve &>/tmp/ollama.log &
    OLLAMA_PID=$!

    # Wait up to 15 s for the server to be ready
    for i in $(seq 1 30); do
        if curl -sf "${OLLAMA_HOST}/api/tags" &>/dev/null; then
            ok "Ollama server ready (PID ${OLLAMA_PID})."
            break
        fi
        sleep 0.5
    done

    if ! curl -sf "${OLLAMA_HOST}/api/tags" &>/dev/null; then
        die "Ollama server did not start within 15 s. Check /tmp/ollama.log."
    fi
fi

# --------------------------------------------------------------------------- #
# 3. Pull required models                                                        #
# --------------------------------------------------------------------------- #
pull_if_missing() {
    local model="$1"
    if ollama list 2>/dev/null | grep -q "^${model%%:*}"; then
        ok "Model already present: ${model}"
    else
        info "Pulling ${model} (this may take several minutes)..."
        ollama pull "${model}"
        ok "Pulled: ${model}"
    fi
}

pull_if_missing "qwen3-vl:4b"
pull_if_missing "qwen3:4b"

# --------------------------------------------------------------------------- #
# 4. Bootstrap .env from .env.example                                           #
# --------------------------------------------------------------------------- #
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(dirname "${SCRIPT_DIR}")"
ENV_FILE="${BACKEND_DIR}/.env"
EXAMPLE_FILE="${BACKEND_DIR}/.env.example"

if [[ ! -f "${ENV_FILE}" ]]; then
    if [[ -f "${EXAMPLE_FILE}" ]]; then
        cp "${EXAMPLE_FILE}" "${ENV_FILE}"
        ok "Created ${ENV_FILE} from .env.example"
        warn "Edit ${ENV_FILE} and set JWT_SECRET before running in production."
    else
        warn ".env.example not found; skipping .env creation."
    fi
else
    ok ".env already exists, not overwritten."
fi

# --------------------------------------------------------------------------- #
# Done                                                                           #
# --------------------------------------------------------------------------- #
echo ""
ok "Setup complete!"
echo ""
echo "  VLM model : qwen3-vl:4b -> ingredient photo recognition"
echo "  LLM model : qwen3:4b    → recipe ideation + re-ranking"
echo "  Endpoint  : http://localhost:11434/v1  (Ollama)"
echo ""
echo "  To start the backend:"
echo "    cd ${BACKEND_DIR}"
echo "    source venv/bin/activate"
echo "    uvicorn app.main:app --reload --port 8000"
echo ""
echo "  To swap models later, edit ${ENV_FILE} and restart uvicorn."
