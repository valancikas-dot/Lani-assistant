"""
Application configuration loaded from environment variables / .env file.
"""

import logging
from typing import List, Literal
from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Service
    APP_NAME: str = "Lani"
    DEBUG: bool = False
    HOST: str = "127.0.0.1"
    PORT: int = 8000

    # ── Environment ──────────────────────────────────────────────────────────
    APP_ENV: Literal["development", "production", "test"] = "development"
    """Runtime environment.
    - development: permissive defaults, deterministic dev keys, verbose logs.
    - production:  fail fast on missing secrets; no dev key fallbacks.
    - test:        same as development but used by the test suite.
    Set APP_ENV=production in your production .env file.
    """

    # CORS – allow Tauri's custom protocol and localhost dev server
    CORS_ORIGINS: List[str] = [
        "http://localhost:1420",  # Vite dev server
        "tauri://localhost",
        "https://tauri.localhost",
        "https://vilca.site",
        "https://www.vilca.site",
    ]

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./assistant.db"

    # Allowed directories for file operations.
    # In .env, set as a comma-separated string:
    #   ALLOWED_DIRECTORIES_RAW=/Users/you/Desktop,/Users/you/Downloads
    # Defaults to empty (deny all) if not set.
    ALLOWED_DIRECTORIES_RAW: str = ""

    # ── AI / LLM ──────────────────────────────────────────────────────────────
    OPENAI_API_KEY: str = ""

    # Primary chat model (2026-03 best: gpt-4.5 for conversation quality)
    LLM_MODEL: str = "gpt-4.5-preview"

    # Heavy reasoning / agent loops / self-edit (o3 = best available 2026-03)
    AGENT_MODEL: str = "o3"

    # Fast cheap routing / classification
    ROUTER_MODEL: str = "gpt-4o-mini"

    # Anthropic (optional – preferred over OpenAI when key is set)
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-3-7-sonnet-20250219"

    # Google Gemini (optional – fast fallback)
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.0-flash"

    # Embedding model (large = better semantic search accuracy)
    EMBEDDING_MODEL: str = "text-embedding-3-large"

    # ElevenLabs (optional – premium TTS with cloned voice)
    ELEVENLABS_API_KEY: str = ""
    ELEVENLABS_VOICE_ID: str = ""   # e.g. "Rachel" voice ID

    # Runway ML (video generation)
    RUNWAY_API_KEY: str = ""
    RUNWAY_MODEL: str = "gen4_turbo"  # Gen-4 Turbo = best 2026-03

    # Suno AI (music generation)
    SUNO_API_KEY: str = ""

    # ── External tool API key aliases (pipeline execution system) ──────────────
    # These are convenience aliases. The external tools check both the alias
    # and the primary key name so you can use either in .env.
    # TTS_API_KEY   → maps to ElevenLabs (preferred over ELEVENLABS_API_KEY)
    TTS_API_KEY: str = ""
    # VIDEO_API_KEY → maps to Runway ML (preferred over RUNWAY_API_KEY)
    VIDEO_API_KEY: str = ""
    # IMAGE_API_KEY → maps to OpenAI Images (preferred over OPENAI_API_KEY)
    IMAGE_API_KEY: str = ""
    # MUSIC_API_KEY → maps to Suno AI (preferred over SUNO_API_KEY)
    MUSIC_API_KEY: str = ""
    # SEARCH_API_KEY → SerpAPI key for richer web search (DuckDuckGo is used without a key)
    SEARCH_API_KEY: str = ""
    # TTS output directory
    TTS_OUTPUT_DIR: str = ""   # default: ~/Desktop/Lani_Audio

    # Language preference
    PREFERRED_LANGUAGE: str = "en"

    # TTS placeholder
    TTS_ENABLED: bool = False
    TTS_VOICE: str = "default"

    # Voice provider selection.
    # Set VOICE_PROVIDER=openai (or another provider name) in .env to enable real STT/TTS.
    # Supported values: "placeholder" (default, no external deps)
    # Future: "openai", "azure", "elevenlabs", "whisper-local"
    VOICE_PROVIDER: str = "placeholder"

    # ── STT (Speech-to-Text) settings ─────────────────────────────────────────
    STT_ENABLED: bool = True
    STT_PROVIDER: str = ""
    MAX_AUDIO_UPLOAD_SECONDS: int = 120
    MAX_AUDIO_UPLOAD_MB: float = 25.0

    # ── Account connectors ────────────────────────────────────────────────────
    # Token encryption
    # Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    CONNECTOR_ENCRYPTION_KEY: str = ""
    """Base64-encoded 32-byte Fernet key.
    - development/test: if empty, a deterministic dev key is derived (NOT for production).
    - production: REQUIRED. App will refuse to start if this is absent.
    """

    SECRET_KEY: str = ""
    """General application secret used as fallback entropy for key derivation.
    - production: REQUIRED if any auth features are enabled.
    """

    # ── Stripe payments ───────────────────────────────────────────────────────
    STRIPE_SECRET_KEY: str = ""
    """Stripe secret key (sk_live_… or sk_test_…)."""

    STRIPE_WEBHOOK_SECRET: str = ""
    """Stripe webhook signing secret (whsec_…). Used to verify webhook payloads."""

    STRIPE_SUCCESS_URL: str = "http://localhost:1420/tokens?payment=success"
    """Redirect URL after successful Stripe checkout."""

    STRIPE_CANCEL_URL: str = "http://localhost:1420/tokens?payment=cancelled"
    """Redirect URL if user cancels Stripe checkout."""

    # Google OAuth 2.0 app credentials
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://127.0.0.1:8000/api/v1/connectors/oauth/callback"

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    @property
    def is_test(self) -> bool:
        return self.APP_ENV == "test"

    @property
    def ALLOWED_DIRECTORIES(self) -> List[str]:
        """Return allowed directories parsed from the raw comma-separated string."""
        raw = self.ALLOWED_DIRECTORIES_RAW.strip()
        if not raw:
            return []
        return [p.strip() for p in raw.split(",") if p.strip()]

    def validate_production_secrets(self) -> None:
        """In production mode, raise if any critical secret is missing."""
        if not self.is_production:
            return
        missing = []
        if not self.CONNECTOR_ENCRYPTION_KEY:
            missing.append("CONNECTOR_ENCRYPTION_KEY")
        if not self.SECRET_KEY:
            missing.append("SECRET_KEY")
        if missing:
            msg = (
                f"[FATAL] APP_ENV=production but required secret(s) are not set: "
                f"{', '.join(missing)}. "
                f"Set them in your .env file or environment before starting the server."
            )
            log.critical(msg)
            raise RuntimeError(msg)

settings = Settings()
