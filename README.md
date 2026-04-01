# Smart Recipe Planner

A smart recipe planning mobile app (Expo, iOS + Android) that eliminates cooking decision fatigue. The app learns user preferences, identifies available ingredients via camera, and delivers personalized recipe suggestions.

## Quick Start

**Already set up?** Pick the command for your environment:

```bash
# Native Linux or macOS
./start_all.sh

# WSL2 (starts cloudflared API tunnel + expo --tunnel so your phone can connect)
./start_all.sh --wsl2
```

To stop everything: `./stop_all.sh` (add `--keep-ollama` to keep models loaded)

---

## Tech Stack

- **Frontend**: Expo SDK 54 (React Native) with Expo Router, NativeWind v4
- **Backend**: Python 3.12+ (FastAPI)
- **AI Models**: Qwen3.5 4B (multimodal text + vision) via [Ollama](https://ollama.com)
- **State Management**: React hooks + Context API
- **Testing**: Jest (frontend), pytest (backend)

## Getting Started

### Prerequisites

- Node.js >= 20 (use nvm: `nvm install 22 && nvm use 22`)
- Python 3.12+
- Expo CLI (`npx expo`)
- ~6 GB free disk space for AI models
- Linux/WSL2 recommended (macOS also works)

### 1. Clone and install dependencies

```bash
git clone <repo-url> && cd recipe_generator

# Frontend
cd frontend
npm install --legacy-peer-deps
cd ..

# Backend
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cd ..
```

### 2. Set up AI models (one-time)

This installs [Ollama](https://ollama.com) and downloads two open-source models (~6 GB total):

```bash
bash backend/scripts/setup_ollama.sh
```

**What it does:**
- Installs Ollama (if not present)
- Pulls `qwen3.5:4b` — multimodal model for recipe ideation, ranking, and ingredient recognition
- Creates `backend/.env` from `.env.example`

> **No GPU?** Both models run on CPU (slower but functional). An NVIDIA GPU with 4+ GB VRAM is recommended.

### 3. Start the models

```bash
bash backend/scripts/start_models.sh
```

This starts the Ollama server and warms up both models. Leave it running.

### 4. Start everything

```bash
./start_all.sh          # native Linux / macOS
./start_all.sh --wsl2   # WSL2: also starts the API tunnel + expo --tunnel
```

`--wsl2` mode:
- Runs `backend/scripts/start_api_tunnel.sh` (downloads `cloudflared` if needed, starts a Cloudflare tunnel, writes the public URL to `frontend/.env`)
- Passes `--tunnel` to Expo so your phone can reach the Metro bundler

Scan the QR code with Expo Go (Android) or the Camera app (iOS).

### Running Tests

**Frontend** (no backend needed):
```bash
cd frontend && npm test
```

**Backend** (requires the backend running per step 4 above):
```bash
cd backend
source venv/bin/activate
pytest tests/ -v                        # all tests (~10 min)
pytest tests/ -v -m "not slow"          # skip LLM pipeline tests
pytest tests/test_infinite_scroll.py    # infinite scroll only
```

## Project Structure

```
├── frontend/                   # Expo mobile app
│   ├── app/                    # Expo Router screens (file-based routing)
│   │   ├── (auth)/             # Welcome + onboarding screens
│   │   ├── (tabs)/             # Main tab screens (discover, saved, history, profile)
│   │   ├── session/            # Session flow (setup, generating)
│   │   └── recipe/[id].js      # Recipe detail screen
│   ├── src/
│   │   ├── components/common/  # Reusable UI components (Button, RecipeCard, etc.)
│   │   ├── context/            # React context providers (Auth, Recipe, Session, SavedRecipes)
│   │   ├── hooks/              # Custom hooks (useRecipes, useVlm, useSavedRecipes, etc.)
│   │   ├── services/           # API client layer (sole HTTP communication)
│   │   ├── utils/              # Pure utility functions (ingredients, time, validation)
│   │   └── constants/          # Static config, meal types, dietary options
│   ├── assets/                 # Images, fonts
│   └── __tests__/              # Tests mirroring src/ structure
│       ├── context/            # Context tests (RecipeContext pagination)
│       ├── hooks/              # Hook tests
│       ├── services/           # Service tests
│       └── utils/              # Utility tests
├── backend/                    # Python FastAPI server
│   ├── app/
│   │   ├── routes/             # API route handlers
│   │   └── services/           # LLM, VLM, pipeline, ranking services
│   ├── tests/                  # pytest integration tests
│   └── scripts/                # Model setup and startup scripts
├── start_all.sh                # Start backend + models in one command
└── stop_all.sh                 # Stop all servers
```

## Environment Variables

```bash
# Created automatically by setup_ollama.sh, or copy manually:
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
```

Key backend variables (see `backend/.env.example` for full docs):

| Variable | Default | Description |
|----------|---------|-------------|
| `VLM_BASE_URL` | `http://localhost:11434/v1` | Ollama endpoint for vision/VLM calls |
| `VLM_MODEL` | `qwen3.5:4b` | Model for ingredient photo recognition |
| `LLM_BASE_URL` | `http://localhost:11434/v1` | Ollama endpoint for text/LLM calls |
| `LLM_MODEL` | `qwen3.5:4b` | Model for recipe ideation + ranking |
| `RANKING_MODE` | `hybrid` | `hybrid` / `rules_only` / `llm_only` |

> Set `VLM_BASE_URL` or `LLM_BASE_URL` to empty to skip AI calls and use mock/fallback data (useful for frontend-only development).
