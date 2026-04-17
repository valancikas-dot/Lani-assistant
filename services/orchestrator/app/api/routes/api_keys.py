"""API Keys route – read (masked) and update service API keys stored in .env."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

# Locate the .env file (two levels up from this file: app/api/routes/ → orchestrator/)
_ENV_PATH = Path(__file__).resolve().parents[3] / ".env"

router = APIRouter()

# ── Key registry ──────────────────────────────────────────────────────────────
# Each entry: (env_var_name, human_label, hint_text)
API_KEY_DEFS: list[tuple[str, str, str]] = [
    (
        "OPENAI_API_KEY",
        "OpenAI",
        "GPT-4o, TTS, DALL·E – sk-proj-…",
    ),
    (
        "TTS_API_KEY",
        "ElevenLabs",
        "TTS fallback / sound effects – sk_…",
    ),
    (
        "SEARCH_API_KEY",
        "Tavily",
        "AI-optimised web search – tvly-…",
    ),
    (
        "VIDEO_API_KEY",
        "Runway ML",
        "Video generation (Gen-4) – key_…",
    ),
    (
        "MUSIC_API_KEY",
        "Music API",
        "Future music generation key",
    ),
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mask(value: str | None) -> str:
    """Return a masked preview: first 10 chars + '••••••••' or empty string."""
    if not value:
        return ""
    if len(value) <= 10:
        return value[:4] + "••••"
    return value[:10] + "••••••••"


def _read_env_file() -> dict[str, str]:
    """Parse .env into a key→value dict (skips comments / blank lines)."""
    result: dict[str, str] = {}
    if not _ENV_PATH.exists():
        return result
    for raw_line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            result[k.strip()] = v.strip()
    return result


def _write_env_key(key: str, value: str) -> None:
    """Set or update a single key=value line in .env (preserves other lines)."""
    lines: list[str] = []
    found = False

    if _ENV_PATH.exists():
        for raw_line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
            stripped = raw_line.strip()
            if stripped.startswith(f"{key}=") or stripped == key:
                lines.append(f"{key}={value}")
                found = True
            else:
                lines.append(raw_line)

    if not found:
        lines.append(f"{key}={value}")

    _ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ── Schemas ───────────────────────────────────────────────────────────────────

class ApiKeyEntry(BaseModel):
    env_var: str
    label: str
    hint: str
    is_set: bool
    masked_value: str  # e.g. "sk-proj-eUFI••••••••"  or ""


class ApiKeysOut(BaseModel):
    keys: list[ApiKeyEntry]


class ApiKeyUpdate(BaseModel):
    updates: dict[str, str]  # env_var → new value (empty string = clear)


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/api-keys", response_model=ApiKeysOut)
async def get_api_keys() -> ApiKeysOut:
    """Return masked current values for all known API keys."""
    env = _read_env_file()
    entries: list[ApiKeyEntry] = []
    for env_var, label, hint in API_KEY_DEFS:
        raw = env.get(env_var, "") or os.environ.get(env_var, "")
        entries.append(
            ApiKeyEntry(
                env_var=env_var,
                label=label,
                hint=hint,
                is_set=bool(raw),
                masked_value=_mask(raw),
            )
        )
    return ApiKeysOut(keys=entries)


@router.post("/api-keys", response_model=ApiKeysOut)
async def update_api_keys(payload: ApiKeyUpdate) -> ApiKeysOut:
    """Update one or more API keys in the .env file."""
    allowed_vars = {d[0] for d in API_KEY_DEFS}
    for env_var, new_value in payload.updates.items():
        if env_var not in allowed_vars:
            continue  # silently ignore unknown vars
        # Also update the running process so changes take effect immediately
        if new_value:
            os.environ[env_var] = new_value
            _write_env_key(env_var, new_value)
        else:
            os.environ.pop(env_var, None)
            _write_env_key(env_var, "")

    return await get_api_keys()
