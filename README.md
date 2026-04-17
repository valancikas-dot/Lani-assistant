# Lani AI

Lani is a local-first personal AI assistant that runs entirely on your machine. Built with Tauri + React on the frontend and FastAPI + Python on the backend.

> **Full install & build guide:** [docs/install.md](docs/install.md)

---

## Quick Start

```bash
# 1. One-time setup
bash scripts/setup.sh

# Optional: quick readiness check
bash scripts/check-readiness.sh

# Simplest local dev start
bash scripts/dev-start.sh

# 2. Start the backend
./scripts/start-backend.sh

# 3. Start the frontend (new terminal)
./scripts/start-frontend.sh
```

For a macOS background backend that auto-restarts through `launchd`:

```bash
./scripts/start-backend-launchd.sh
```

To stop that background service later:

```bash
./scripts/stop-backend-prod.sh
```

To uninstall the background `launchd` service completely:

```bash
./scripts/uninstall-backend-launchd.sh
```

If you want speaker fingerprinting / voice biometrics features, install the optional backend dependency group:

```bash
cd services/orchestrator
source .venv/bin/activate
poetry install --with voice
```

If this optional group is not installed, the app still starts in a degraded mode and surfaces that status in Diagnostics.

For the full setup walkthrough including environment variables, production build steps, and troubleshooting see **[docs/install.md](docs/install.md)**.

---

## Features

| Feature | Status |
|---------|--------|
| Chat with file/doc/web tools | ✅ |
| Multi-step task planning | ✅ |
| Cross-tool automation workflows | ✅ |
| Voice STT / TTS (push-to-talk) | ✅ |
| Wake-word session | ✅ |
| Account Connectors (Google Drive, Gmail, Calendar) | ✅ |
| Computer Operator (open apps, windows) | ✅ |
| Builder Mode (project scaffolding) | ✅ |
| Approval gate for sensitive actions | ✅ |
| Memory / context persistence | ✅ |
| Audit log | ✅ |
| Security / speaker verification | ✅ |
| Diagnostics / System Status page | ✅ |
| i18n (English + Lithuanian) | ✅ |
| Native desktop app (Tauri) | ✅ |

---

## Architecture

```
personal-ai-assistant/
├── apps/
│   └── desktop/               # Tauri + React + Vite desktop app
│       ├── src/
│       │   ├── app/           # Root App component + router
│       │   ├── components/    # UI components
│       │   ├── hooks/         # Custom React hooks
│       │   ├── i18n/          # Localisation (en, lt)
│       │   ├── lib/           # api.ts + types.ts
│       │   ├── pages/         # Chat, Approvals, Builder, Connectors,
│       │   │                  # Operator, Security, Diagnostics, Settings, Memory, Logs
│       │   ├── stores/        # Zustand state
│       │   └── styles/        # global.css
│       └── src-tauri/         # Rust / Tauri shell
│
├── services/
│   └── orchestrator/          # FastAPI backend
│       └── app/
│           ├── api/routes/    # health, commands, approvals, settings, logs,
│           │                  # voice, plans, memory, research, security,
│           │                  # wake, builder, connectors, operator, workflow, system
│           ├── core/          # config, database, logging
│           ├── models/        # SQLAlchemy ORM models
│           ├── schemas/       # Pydantic schemas
│           ├── services/      # task_planner, plan_executor, workflow_planner,
│           │                  # workflow_executor, memory_service, voice_service, …
│           └── tools/         # file_tools, doc_tools, research_tools, connector_tools, …
│
├── docs/
│   ├── install.md             # ← Full install guide
│   ├── architecture.md
│   └── voice-integration.md
│
└── scripts/
    ├── setup.sh
    ├── start-backend.sh
    ├── start-frontend.sh
    └── build-desktop.sh       # ← Release build script
```

---

## Development

### Backend tests

```bash
cd services/orchestrator
source .venv/bin/activate
python -m pytest tests/test_smoke.py -q
# Expected: smoke suite passes
```

### Frontend type-check + tests

```bash
cd apps/desktop
npx tsc --noEmit
npx vitest run
```

### Build desktop app for local distribution

```bash
./scripts/build-desktop.sh
```

---

## Diagnostics

Open the **🩺 Diagnostics** page in the sidebar to see a live system readiness report:
backend connectivity, database, encryption, voice provider, microphone, connected accounts, and more.

The diagnostics payload also includes `voice_biometrics` to indicate whether optional speaker-verification dependencies are available.

The endpoint is also available at: `GET http://127.0.0.1:8000/api/v1/system/status`

---

## License

MIT


---

## Architecture

```
personal-ai-assistant/
├── apps/
│   └── desktop/               # Tauri + React + Vite desktop app
│       ├── src/
│       │   ├── app/           # Root App component + router
│       │   ├── components/    # UI components (chat, approvals, logs, settings, layout)
│       │   ├── hooks/         # Custom React hooks
│       │   ├── lib/           # api.ts (HTTP client) + types.ts (shared contracts)
│       │   ├── pages/         # Page-level components (Chat, Approvals, Logs, Settings)
│       │   ├── stores/        # Zustand state stores
│       │   └── styles/        # global.css
│       └── src-tauri/         # Rust / Tauri shell
│
├── services/
│   └── orchestrator/          # FastAPI backend
│       └── app/
│           ├── api/routes/    # health, commands, approvals, settings, logs
│           ├── core/          # config, database, logging
│           ├── models/        # SQLAlchemy ORM models
│           ├── schemas/       # Pydantic request/response schemas
│           ├── services/      # command_router, approval_service, audit_service, memory_service
│           └── tools/         # file_tools, doc_tools, presentation_tools, registry
│
├── packages/
│   └── shared/                # Shared TypeScript types
│
├── docs/                      # Architecture docs
└── scripts/                   # Setup and run scripts
```

---

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Python | ≥ 3.11 | [python.org](https://python.org) |
| Node.js | ≥ 18 | [nodejs.org](https://nodejs.org) |
| Rust | stable | `curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \| sh` |
| Tauri CLI | ≥ 1.6 | `cargo install tauri-cli` |

---

## Quick Start

### 1. Clone & enter the project

```bash
cd personal-ai-assistant
```

### 2. One-time setup

```bash
bash scripts/setup.sh
```

This will:
- Create a Python venv and install all Python dependencies
- Copy `.env.example` → `.env`
- Install npm packages for the frontend

### 3. Configure allowed directories

Edit `services/orchestrator/.env` and set the paths Lani may access:

```env
ALLOWED_DIRECTORIES_RAW=/Users/you/Desktop,/Users/you/Downloads
```

> ⚠️ Lani will **refuse all file operations** if this is empty.

### 4. Start the backend

```bash
cd services/orchestrator
source .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Backend API docs: http://127.0.0.1:8000/docs

### 5. Start the frontend (browser preview)

In a new terminal:

```bash
cd apps/desktop
npm run dev
```

Open http://localhost:1420

### 6. Start as a native desktop app (Tauri)

```bash
cd apps/desktop
npm run tauri:dev
```

> Tauri requires Rust and the platform dependencies listed at https://tauri.app/v1/guides/getting-started/prerequisites

---

## Available Commands (Chat UI)

| Command example | Tool invoked |
|---|---|
| `create folder ~/Desktop/Projects` | `create_folder` |
| `create file ~/Desktop/notes.txt with content Hello` | `create_file` |
| `move ~/Desktop/old.txt to ~/Desktop/archive/old.txt` | `move_file` *(approval required)* |
| `sort downloads in ~/Downloads` | `sort_downloads` *(approval required)* |
| `read ~/Documents/report.pdf` | `read_document` |
| `summarize ~/Documents/report.pdf` | `summarize_document` |
| `create presentation "Q1 Review" with outline Sales, Engineering, Marketing` | `create_presentation` |
| `search for latest AI news` | `web_search` |
| `research and summarize quantum computing` | `research_and_prepare_brief` |

---

## Backend API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/health` | Health check |
| POST | `/api/v1/commands` | Submit a command |
| GET | `/api/v1/tools` | List available tools |
| GET | `/api/v1/approvals` | List pending approvals |
| POST | `/api/v1/approvals/{id}` | Approve or deny an action |
| GET | `/api/v1/settings` | Get user settings |
| PATCH | `/api/v1/settings` | Update user settings |
| GET | `/api/v1/logs` | Get audit log |

---

## Security model

- All file operations are restricted to `ALLOWED_DIRECTORIES`
- Actions marked `requires_approval = True` (move_file, sort_downloads) return `approval_required` status and are queued until the user confirms via the Approvals page
- Every action (success, error, approval) is recorded in the SQLite `audit_logs` table
- No action silently modifies the filesystem

---

## Environment Variables

Copy `services/orchestrator/.env.example` to `.env` and configure:

| Variable | Default | Description |
|---|---|---|
| `DEBUG` | `false` | Enable verbose logging |
| `HOST` | `127.0.0.1` | Server bind host |
| `PORT` | `8000` | Server bind port |
| `DATABASE_URL` | `sqlite+aiosqlite:///./assistant.db` | SQLite DB path |
| `ALLOWED_DIRECTORIES` | *(empty – must set)* | Colon-separated allowed paths |
| `OPENAI_API_KEY` | *(empty)* | Optional – enables LLM-powered intent parsing |
| `LLM_MODEL` | `gpt-4o` | LLM model when API key is set |
| `PREFERRED_LANGUAGE` | `en` | User language preference |
| `TTS_ENABLED` | `false` | Text-to-speech placeholder |

---

## Development

### Backend tests

```bash
cd services/orchestrator
source .venv/bin/activate
pytest
```

### Frontend type-check

```bash
cd apps/desktop
npx tsc --noEmit
```

### Lint backend

```bash
cd services/orchestrator
ruff check app/
```

---

## Next Steps – Voice Integration

The following steps are needed to add voice input/output to Lani:

1. **Speech-to-Text (STT)**
   - Add a `VoiceInput` React component using the Web Speech API (`SpeechRecognition`) or Tauri's OS audio APIs
   - On transcript ready, call the same `sendCommand()` function already wired in ChatPage

2. **Text-to-Speech (TTS)**
   - The `TTS_ENABLED` / `TTS_VOICE` settings placeholders are already in the backend
   - Implement `SpeechSynthesis` (browser built-in) or integrate `ElevenLabs` / `Coqui TTS` for higher quality
   - Speak the `result.message` from each `CommandResponse`

3. **Wake word (optional)**
   - Integrate `Porcupine` (offline, on-device) via a Python background thread
   - Emit a Tauri event to the frontend when the wake word is detected

4. **Hook locations**
   - Frontend: `apps/desktop/src/components/chat/ChatInput.tsx` – add mic button
   - Backend: `services/orchestrator/app/services/memory_service.py` – persist voice sessions
   - Config: `services/orchestrator/.env` – TTS_VOICE, TTS_ENABLED already present

---

## Roadmap

- [ ] LLM-powered intent parsing (replace keyword regex with function calling)
- [ ] Voice input (Web Speech API / Tauri audio)
- [ ] Voice output (TTS)
- [ ] Multi-session conversation memory
- [ ] Calendar / reminder integration
- [ ] Plugin/extension system for third-party tools

---

## License

MIT
