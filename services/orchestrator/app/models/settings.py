"""ORM model for persisted user settings."""

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class UserSettings(Base):
    """Single-row table storing the current user's preferences."""

    __tablename__ = "user_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    allowed_directories: Mapped[str] = mapped_column(
        Text, default="", nullable=False
    )  # JSON array serialised as text
    # Multilingual & UI settings
    preferred_language: Mapped[str] = mapped_column(String(10), default="lt", nullable=False)
    ui_language: Mapped[str] = mapped_column(String(10), default="lt", nullable=False)
    assistant_language: Mapped[str] = mapped_column(String(10), default="lt", nullable=False)
    speech_recognition_language: Mapped[str] = mapped_column(String(10), default="lt-LT", nullable=False)
    speech_output_language: Mapped[str] = mapped_column(String(10), default="lt-LT", nullable=False)
    multilingual_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Text-to-speech / voice
    tts_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    tts_voice: Mapped[str] = mapped_column(String(60), default="default", nullable=False)
    tts_provider: Mapped[str] = mapped_column(String(60), default="", nullable=False)
    """Override for TTS provider; empty = use server default."""

    # Voice / speaker verification settings
    voice_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    speaker_verification_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    voice_lock_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    security_mode: Mapped[str] = mapped_column(String(40), default="disabled", nullable=False)
    fallback_pin_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    fallback_passphrase_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    fallback_pin_hash: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    fallback_passphrase_hint: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    allow_text_access_without_voice_verification: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    require_verification_for_sensitive_actions_only: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    max_failed_voice_attempts: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    lock_on_failed_verification: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    first_run_complete: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Runtime counters (persisted so lockouts survive restarts)
    failed_voice_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # ── Wake-word / voice-session settings ──────────────────────────────────
    wake_word_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    primary_wake_phrase: Mapped[str] = mapped_column(String(80), default="Lani", nullable=False)
    secondary_wake_phrase: Mapped[str] = mapped_column(String(80), default="Hey Lani", nullable=False)
    voice_session_timeout_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    require_reverification_after_timeout: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    wake_mode: Mapped[str] = mapped_column(String(40), default="manual", nullable=False)

    # ── STT (Speech-to-Text) settings ───────────────────────────────────────
    stt_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    """Whether the /voice/transcribe endpoint is active for this user."""

    stt_provider: Mapped[str] = mapped_column(String(60), default="", nullable=False)
    """Override for VOICE_PROVIDER; empty = use server default."""

    max_audio_upload_seconds: Mapped[int] = mapped_column(Integer, default=120, nullable=False)
    """Maximum recording duration the user is allowed to send (seconds)."""

    max_audio_upload_mb: Mapped[float] = mapped_column(
        Integer, default=25, nullable=False
    )
    """Maximum audio upload size in megabytes."""

