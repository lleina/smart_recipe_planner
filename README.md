# Smart Recipe Planner

A smart recipe planning mobile app (Expo, iOS + Android) that eliminates cooking decision fatigue. The app learns user preferences, identifies available ingredients via camera, and delivers personalized recipe suggestions.

## Quick Start

**Already set up?** Run everything at once:
```bash
cd ~/recipe_generator
./start_all.sh
```
To stop all servers: `./stop_all.sh`

For detailed server management (troubleshooting, background processes, etc.), see [SERVER_MANAGEMENT.md](./SERVER_MANAGEMENT.md).

---

## Tech Stack

- **Frontend**: Expo SDK 54 (React Native) with Expo Router, NativeWind v4
- **Backend**: Python 3.12+ (FastAPI)
- **AI Models**: Qwen3 4B (text) + Qwen3-VL 4B (vision) via [Ollama](https://ollama.com)
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
- Pulls `qwen3:4b` — text model for recipe ideation + ranking
- Pulls `qwen3-vl:4b` — vision model for ingredient recognition from photos
- Creates `backend/.env` from `.env.example`

> **No GPU?** Both models run on CPU (slower but functional). An NVIDIA GPU with 4+ GB VRAM is recommended.

### 3. Start the models

```bash
bash backend/scripts/start_models.sh
```

This starts the Ollama server and warms up both models. Leave it running.

### 4. Start the backend

```bash
cd backend
source venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

### 5. Start the frontend

```bash
cd frontend
npx expo start --tunnel    # use --tunnel for WSL2
```

Scan the QR code with Expo Go (Android) or Camera app (iOS).

### Running Tests

**Frontend** (no backend needed):
```bash
cd ~/recipe_generator/frontend && npm test
```

**Backend** (requires backend + Ollama running via `./start_all.sh`):
```bash
cd ~/recipe_generator/backend
source venv/bin/activate
pytest tests/ -v                        # all tests (~10 min)
pytest tests/ -v -m "not slow"          # skip LLM pipeline tests
pytest tests/test_infinite_scroll.py    # infinite scroll only
```

## Project Structure

```
recipe_generator/
├── frontend/              # Expo mobile app
│   ├── app/               # Expo Router screens (file-based routing)
│   ├── src/
│   │   ├── components/    # Reusable UI components by feature domain
│   │   ├── hooks/         # Custom React hooks (primary state management)
│   │   ├── services/      # API client layer (sole HTTP communication)
│   │   ├── utils/         # Pure utility functions
│   │   ├── constants/     # Static data and configuration
│   │   └── context/       # React context providers (auth, session)
│   ├── assets/            # Static images, fonts
│   └── __tests__/         # Tests mirroring src/ structure
├── backend/               # Python API server
│   ├── app/               # FastAPI routes, models, services
│   └── scripts/           # Model setup and startup scripts
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
| `VLM_BASE_URL` | `http://localhost:11434/v1` | Ollama endpoint for vision model |
| `VLM_MODEL` | `qwen3-vl:4b` | Vision model for ingredient photos |
| `LLM_BASE_URL` | `http://localhost:11434/v1` | Ollama endpoint for text model |
| `LLM_MODEL` | `qwen3:4b` | Text model for ideation + ranking |
| `RANKING_MODE` | `hybrid` | `hybrid` / `rules_only` / `llm_only` |

> Set `VLM_BASE_URL` or `LLM_BASE_URL` to empty to skip AI calls and use mock/fallback data (useful for frontend-only development).
