# Lani – Local Install, Build & Troubleshooting Guide

> **Status:** Lani 0.1.0 — local development & personal use release.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Quick Start (Development)](#quick-start-development)
3. [Environment Variables](#environment-variables)
4. [First-Run Behaviour](#first-run-behaviour)
5. [Building the Desktop App (Release)](#building-the-desktop-app-release)
6. [Production Checklist](#production-checklist)
7. [Diagnostics / System Status](#diagnostics--system-status)
8. [Troubleshooting](#troubleshooting)

---

## Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| Node.js | ≥ 18 | `node --version` |
| Python | ≥ 3.11 | `python3 --version` |
| Rust | stable | `rustup show` (required for Tauri) |
| npm | ≥ 9 | comes with Node |
| Xcode CLI (macOS) | any | `xcode-select --install` |
| WebKit (Linux) | libwebkit2gtk-4.0-dev | `apt install libwebkit2gtk-4.0-dev` |

---

## Quick Start (Development)

### 1. Clone and install

```bash
git clone <your-repo>
cd personal-ai-assistant
bash scripts/setup.sh
```

### 2. Configure the backend

```bash
cd services/orchestrator
cp .env.example .env   # edit with your values (see Environment Variables below)
```

The setup script creates `services/orchestrator/.venv`, installs the backend
dependencies via Poetry, and installs the desktop frontend npm packages.

By default this installs the **core backend dependencies**.
Voice biometrics (speaker fingerprinting) uses an optional dependency group.

### 2b. Optional: enable voice biometrics dependencies

If you want voice-profile fingerprinting and strict speaker-verification checks,
install the optional `voice` dependency group:

```bash
cd services/orchestrator
source .venv/bin/activate
poetry install --with voice
```

### 3. Start the backend

```bash
./scripts/start-backend.sh
# Runs FastAPI on http://127.0.0.1:8000
```

### 3b. Optional macOS auto-start backend via launchd

```bash
./scripts/start-backend-launchd.sh
```

This installs a per-user `launchd` agent in `~/Library/LaunchAgents/` and keeps
the backend running in the background.

To stop it:

```bash
./scripts/stop-backend-prod.sh
```

To uninstall it completely:

```bash
./scripts/uninstall-backend-launchd.sh
```

### 4. Start the frontend (dev mode)

```bash
./scripts/start-frontend.sh
# Starts the Vite dev server for the desktop frontend
```

The frontend connects to `http://127.0.0.1:8000` by default.  
Override with `VITE_API_BASE_URL=http://your-host:port` in `apps/desktop/.env`.

---

## Environment Variables

All backend variables live in `services/orchestrator/.env`.  
Create it from the example: `cp .env.example .env`

### Core

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_ENV` | `development` | Set to `production` for release builds. In production mode missing secrets cause a fatal startup error. |
| `DEBUG` | `false` | Enable SQLAlchemy query logging and FastAPI debug mode. |
| `HOST` | `127.0.0.1` | Bind address. |
| `PORT` | `8000` | Listen port. |
| `DATABASE_URL` | `sqlite+aiosqlite:///./assistant.db` | SQLite database path. |

### AI / LLM

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | For AI features | Your OpenAI API key. |
| `LLM_MODEL` | No (default: `gpt-4o`) | Model used for planning and task execution. |

### Voice

| Variable | Default | Description |
|----------|---------|-------------|
| `VOICE_PROVIDER` | `placeholder` | Set to `openai` to enable real STT/TTS. |
| `TTS_ENABLED` | `false` | Master TTS on/off switch. |
| `STT_ENABLED` | `true` | Master STT on/off switch. |
| `MAX_AUDIO_UPLOAD_SECONDS` | `120` | Reject audio longer than this. |
| `MAX_AUDIO_UPLOAD_MB` | `25.0` | Reject audio files larger than this. |

### Security

| Variable | Required in prod | Description |
|----------|-----------------|-------------|
| `CONNECTOR_ENCRYPTION_KEY` | Yes | 32-byte Fernet key. Generate: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `SECRET_KEY` | Yes | General application secret. Generate: `openssl rand -hex 32` |

### Connectors (optional)

| Variable | Description |
|----------|-------------|
| `GOOGLE_CLIENT_ID` | Google OAuth app client ID. |
| `GOOGLE_CLIENT_SECRET` | Google OAuth app client secret. |
| `GOOGLE_REDIRECT_URI` | OAuth callback URL (default: `http://127.0.0.1:8000/api/v1/connectors/oauth/callback`). |

### File Access

| Variable | Default | Description |
|----------|---------|-------------|
| `ALLOWED_DIRECTORIES_RAW` | `""` (deny all) | Comma-separated list of directories the assistant may read/write. Example: `/Users/you/Desktop,/Users/you/Downloads` |

---

## First-Run Behaviour

On first launch Lani shows a **setup wizard** that walks through:

1. UI language selection
2. Assistant language selection
3. Speech recognition / output language
4. Voice enable/disable
5. (Optional) Voice profile enrollment
6. Security mode
7. Allowed directories
8. Finish — sets `first_run_complete = true` in the database

If the setup wizard is interrupted (e.g. you close the window), it resumes from the beginning the next time the app starts, until `first_run_complete` is set.

To **reset** the first-run experience:

```bash
# Option A: delete the database (all data lost)
rm services/orchestrator/assistant.db

# Option B: reset only the flag via API
curl -X PUT http://127.0.0.1:8000/api/v1/settings \
  -H 'Content-Type: application/json' \
  -d '{"first_run_complete": false}'
```

---

## Degraded Mode (Missing Optional Voice Biometrics Dependency)

If optional voice biometrics dependencies are not installed, backend startup still succeeds.

What changes in this mode:

- Voice biometrics is reported as unavailable in diagnostics.
- Features that require speaker fingerprinting are blocked with a clear reason.
- In strict security mode, verification does **not** silently pass when biometrics is unavailable.

This behavior is intentional so local development can proceed without forcing all optional native/scientific packages.

---

## Building the Desktop App (Release)

Use the build script:

```bash
./scripts/build-desktop.sh          # release build
./scripts/build-desktop.sh --debug  # debug build
```

What the script does:

1. Installs npm dependencies
2. Runs `tsc --noEmit` (type-check)
3. Runs `vitest run` (frontend tests)
4. Runs `tauri build`

**Output locations:**

| Platform | Path |
|----------|------|
| macOS | `apps/desktop/src-tauri/target/release/bundle/macos/Lani.app` |
| macOS DMG | `apps/desktop/src-tauri/target/release/bundle/dmg/Lani_0.1.0_x64.dmg` |
| Windows | `apps/desktop/src-tauri/target/release/bundle/msi/` |
| Linux AppImage | `apps/desktop/src-tauri/target/release/bundle/appimage/` |

### Tauri configuration

`apps/desktop/src-tauri/tauri.conf.json`:

```json
{
  "package": { "productName": "Lani", "version": "0.1.0" },
  "tauri": {
    "bundle": {
      "identifier": "com.lani.ai",
      "icon": [ "icons/32x32.png", "icons/128x128.png", ... ]
    }
  }
}
```

To change the version, update both `tauri.conf.json` → `package.version` and `apps/desktop/package.json` → `version`.

---

## Production Checklist

Before distributing a release build:

- [ ] `APP_ENV=production` in `.env`
- [ ] `CONNECTOR_ENCRYPTION_KEY` set (32-byte Fernet key)
- [ ] `SECRET_KEY` set (`openssl rand -hex 32`)
- [ ] `OPENAI_API_KEY` set (if AI features are enabled)
- [ ] `ALLOWED_DIRECTORIES_RAW` configured to safe paths
- [ ] `DEBUG=false`
- [ ] App icon files present in `apps/desktop/src-tauri/icons/`
- [ ] `tsc --noEmit` passes with 0 errors
- [ ] `vitest run` passes
- [ ] `pytest tests/test_smoke.py -q` passes
- [ ] Diagnostics page shows all green (or expected warnings)

---

## Diagnostics / System Status

Open the **Diagnostics** page (🩺 in the sidebar) to see a live readiness report including:

| Check | What it verifies |
|-------|-----------------|
| Backend Connection | Frontend can reach the FastAPI server |
| Microphone | Browser microphone permission |
| Platform | OS type and version |
| Database | SQLite is reachable |
| Token Encryption | `CONNECTOR_ENCRYPTION_KEY` is set and valid |
| OpenAI API Key | `OPENAI_API_KEY` is set |
| Secret Key | `SECRET_KEY` is set |
| Voice Provider | `VOICE_PROVIDER` is not `placeholder` |
| Voice Biometrics | Optional speaker-fingerprint dependency is available |
| STT / TTS | Enabled/disabled flags |
| Voice Profile | At least one profile is enrolled |
| Connected Accounts | Active OAuth connector accounts |

The backend endpoint is: `GET /api/v1/system/status`

Quick check from terminal:

```bash
curl -s http://127.0.0.1:8000/api/v1/system/status | python -m json.tool
```

Look for the `voice_biometrics` component (`ok`, `label`, `detail`) to confirm whether optional biometrics is available.

---

## Troubleshooting

### "Backend offline" banner on startup

The frontend cannot reach `http://127.0.0.1:8000`.

```bash
# Start the backend:
./scripts/start-backend.sh
```

Check that no other process is using port 8000:

```bash
lsof -i :8000
```

### "Using dev key" encryption warning

`CONNECTOR_ENCRYPTION_KEY` is not set. This is normal for local development.  
For production: generate a key and set it in `.env`:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### First-run wizard shows every launch

The setup wizard shows when `first_run_complete` is `false` in the database.  
If it keeps appearing, check that the backend is running when you complete the wizard (settings are persisted via API call).

### Voice features not working

1. Check `VOICE_PROVIDER` in `.env` — set to `openai` for real STT/TTS.
2. Check `OPENAI_API_KEY` is set.
3. Open Diagnostics page and check the Voice Provider, Voice Biometrics, and STT/TTS tiles.
4. If Voice Biometrics is unavailable and you need speaker verification, install optional deps:

```bash
cd services/orchestrator
source .venv/bin/activate
poetry install --with voice
```

5. Check microphone permission — granted in the browser/OS.

### Database errors on startup

```bash
# Delete and recreate:
rm services/orchestrator/assistant.db
./scripts/start-backend.sh   # recreates tables on startup
```

### TypeScript errors in development

```bash
cd apps/desktop && npx tsc --noEmit
```

### Backend test failures

```bash
cd services/orchestrator && python -m pytest tests/test_smoke.py -q
```

Expected: smoke suite completes successfully.
