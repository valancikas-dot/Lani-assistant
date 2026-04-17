"""Pydantic schemas for user settings."""

from typing import List
from pydantic import BaseModel, ConfigDict


class SettingsOut(BaseModel):
    """Settings payload returned to the frontend."""
    model_config = ConfigDict(from_attributes=True)

    allowed_directories: List[str]
    preferred_language: str
    ui_language: str
    assistant_language: str
    speech_recognition_language: str
    speech_output_language: str
    multilingual_enabled: bool = False

    tts_enabled: bool
    tts_voice: str
    tts_provider: str = ""

    # ── Voice / security settings
    voice_enabled: bool = False
    speaker_verification_enabled: bool = False
    voice_lock_enabled: bool = False
    security_mode: str = "disabled"
    fallback_pin_enabled: bool = False
    fallback_passphrase_enabled: bool = False
    allow_text_access_without_voice_verification: bool = True
    require_verification_for_sensitive_actions_only: bool = False
    max_failed_voice_attempts: int = 5
    lock_on_failed_verification: bool = True
    first_run_complete: bool = False
    failed_voice_attempts: int = 0

    # ── Wake-word settings ──────────────────────────────────────────────────
    wake_word_enabled: bool = False
    primary_wake_phrase: str = "Lani"
    secondary_wake_phrase: str = "Hey Lani"
    voice_session_timeout_seconds: int = 0
    require_reverification_after_timeout: bool = False
    wake_mode: str = "manual"

    # ── STT settings ────────────────────────────────────────────────────────
    stt_enabled: bool = True
    stt_provider: str = ""
    max_audio_upload_seconds: int = 120
    max_audio_upload_mb: float = 25.0

class SettingsUpdate(BaseModel):
    """Partial update payload for settings."""
    allowed_directories: List[str] | None = None
    preferred_language: str | None = None
    ui_language: str | None = None
    assistant_language: str | None = None
    speech_recognition_language: str | None = None
    speech_output_language: str | None = None
    multilingual_enabled: bool | None = None

    tts_enabled: bool | None = None
    tts_voice: str | None = None
    tts_provider: str | None = None

    voice_enabled: bool | None = None
    speaker_verification_enabled: bool | None = None
    voice_lock_enabled: bool | None = None
    security_mode: str | None = None
    fallback_pin_enabled: bool | None = None
    fallback_passphrase_enabled: bool | None = None
    allow_text_access_without_voice_verification: bool | None = None
    require_verification_for_sensitive_actions_only: bool | None = None
    max_failed_voice_attempts: int | None = None
    lock_on_failed_verification: bool | None = None
    first_run_complete: bool | None = None
    failed_voice_attempts: int | None = None

    # ── Wake-word settings ──────────────────────────────────────────────────
    wake_word_enabled: bool | None = None
    primary_wake_phrase: str | None = None
    secondary_wake_phrase: str | None = None
    voice_session_timeout_seconds: int | None = None
    require_reverification_after_timeout: bool | None = None
    wake_mode: str | None = None

    # ── STT settings ────────────────────────────────────────────────────────
    stt_enabled: bool | None = None
    stt_provider: str | None = None
    max_audio_upload_seconds: int | None = None
    max_audio_upload_mb: float | None = None
