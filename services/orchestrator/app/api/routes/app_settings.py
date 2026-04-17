"""Settings route – read and update user application settings."""

import json

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.settings import UserSettings
from app.schemas.settings import SettingsOut, SettingsUpdate
from app.utils.languages import SUPPORTED_LANGUAGES

router = APIRouter()


async def _get_or_create_settings(db: AsyncSession) -> UserSettings:
    """Return the single settings row, creating it if it doesn't exist."""
    result = await db.execute(select(UserSettings).where(UserSettings.id == 1))
    row = result.scalar_one_or_none()
    if row is None:
        row = UserSettings(id=1)
        db.add(row)
        await db.flush()
    return row


def _row_to_out(row: UserSettings) -> SettingsOut:
    dirs = json.loads(row.allowed_directories) if row.allowed_directories else []
    return SettingsOut(
        allowed_directories=dirs,
        preferred_language=row.preferred_language,
        ui_language=row.ui_language,
        assistant_language=row.assistant_language,
        speech_recognition_language=row.speech_recognition_language,
        speech_output_language=row.speech_output_language,
        multilingual_enabled=bool(row.multilingual_enabled),

        tts_enabled=bool(row.tts_enabled),
        tts_voice=row.tts_voice,
        tts_provider=getattr(row, "tts_provider", "") or "",

        # voice / security
        voice_enabled=bool(row.voice_enabled),
        speaker_verification_enabled=bool(row.speaker_verification_enabled),
        voice_lock_enabled=bool(row.voice_lock_enabled),
        security_mode=row.security_mode,
        fallback_pin_enabled=bool(row.fallback_pin_enabled),
        fallback_passphrase_enabled=bool(row.fallback_passphrase_enabled),
        allow_text_access_without_voice_verification=bool(row.allow_text_access_without_voice_verification),
        require_verification_for_sensitive_actions_only=bool(row.require_verification_for_sensitive_actions_only),
        max_failed_voice_attempts=int(row.max_failed_voice_attempts),
        lock_on_failed_verification=bool(row.lock_on_failed_verification),
        first_run_complete=bool(row.first_run_complete),
        # wake-word
        wake_word_enabled=bool(row.wake_word_enabled),
        primary_wake_phrase=row.primary_wake_phrase or "Lani",
        secondary_wake_phrase=row.secondary_wake_phrase or "Hey Lani",
        voice_session_timeout_seconds=int(row.voice_session_timeout_seconds if row.voice_session_timeout_seconds is not None else 0),
        require_reverification_after_timeout=bool(row.require_reverification_after_timeout),
        wake_mode=row.wake_mode or "manual",
        # STT
        stt_enabled=bool(getattr(row, "stt_enabled", True)),
        stt_provider=getattr(row, "stt_provider", "") or "",
        max_audio_upload_seconds=int(getattr(row, "max_audio_upload_seconds", 120) or 120),
        max_audio_upload_mb=float(getattr(row, "max_audio_upload_mb", 25) or 25.0),
    )


@router.get("/settings", response_model=SettingsOut)
async def get_settings(db: AsyncSession = Depends(get_db)) -> SettingsOut:
    """Return current user settings."""
    row = await _get_or_create_settings(db)
    return _row_to_out(row)


@router.get("/settings/languages")
async def list_languages():
    """Return the list of supported languages (code/display/native)."""
    return SUPPORTED_LANGUAGES


@router.patch("/settings", response_model=SettingsOut)
async def update_settings(
    payload: SettingsUpdate,
    db: AsyncSession = Depends(get_db),
) -> SettingsOut:
    """Partially update user settings."""
    row = await _get_or_create_settings(db)

    if payload.allowed_directories is not None:
        row.allowed_directories = json.dumps(payload.allowed_directories)
    if payload.preferred_language is not None:
        row.preferred_language = payload.preferred_language
    if payload.tts_enabled is not None:
        row.tts_enabled = bool(payload.tts_enabled)
    if payload.tts_voice is not None:
        row.tts_voice = payload.tts_voice
    if payload.tts_provider is not None:
        row.tts_provider = payload.tts_provider
    # multilingual / UI
    if payload.ui_language is not None:
        row.ui_language = payload.ui_language
    if payload.assistant_language is not None:
        row.assistant_language = payload.assistant_language
    if payload.speech_recognition_language is not None:
        row.speech_recognition_language = payload.speech_recognition_language
    if payload.speech_output_language is not None:
        row.speech_output_language = payload.speech_output_language
    if payload.multilingual_enabled is not None:
        row.multilingual_enabled = bool(payload.multilingual_enabled)

    # voice / security
    if payload.voice_enabled is not None:
        row.voice_enabled = bool(payload.voice_enabled)
    if payload.speaker_verification_enabled is not None:
        row.speaker_verification_enabled = bool(payload.speaker_verification_enabled)
    if payload.voice_lock_enabled is not None:
        row.voice_lock_enabled = bool(payload.voice_lock_enabled)
    if payload.security_mode is not None:
        row.security_mode = payload.security_mode
    if payload.fallback_pin_enabled is not None:
        row.fallback_pin_enabled = bool(payload.fallback_pin_enabled)
    if payload.fallback_passphrase_enabled is not None:
        row.fallback_passphrase_enabled = bool(payload.fallback_passphrase_enabled)
    if payload.allow_text_access_without_voice_verification is not None:
        row.allow_text_access_without_voice_verification = bool(payload.allow_text_access_without_voice_verification)
    if payload.require_verification_for_sensitive_actions_only is not None:
        row.require_verification_for_sensitive_actions_only = bool(payload.require_verification_for_sensitive_actions_only)
    if payload.max_failed_voice_attempts is not None:
        row.max_failed_voice_attempts = int(payload.max_failed_voice_attempts)
    if payload.lock_on_failed_verification is not None:
        row.lock_on_failed_verification = bool(payload.lock_on_failed_verification)
    if payload.first_run_complete is not None:
        row.first_run_complete = bool(payload.first_run_complete)
    if payload.failed_voice_attempts is not None:
        row.failed_voice_attempts = int(payload.failed_voice_attempts)
    # wake-word
    if payload.wake_word_enabled is not None:
        row.wake_word_enabled = bool(payload.wake_word_enabled)
    if payload.primary_wake_phrase is not None:
        row.primary_wake_phrase = payload.primary_wake_phrase
    if payload.secondary_wake_phrase is not None:
        row.secondary_wake_phrase = payload.secondary_wake_phrase
    if payload.voice_session_timeout_seconds is not None:
        row.voice_session_timeout_seconds = int(payload.voice_session_timeout_seconds)
    if payload.require_reverification_after_timeout is not None:
        row.require_reverification_after_timeout = bool(payload.require_reverification_after_timeout)
    if payload.wake_mode is not None:
        row.wake_mode = payload.wake_mode
    # STT
    if payload.stt_enabled is not None:
        row.stt_enabled = bool(payload.stt_enabled)
    if payload.stt_provider is not None:
        row.stt_provider = payload.stt_provider
    if payload.max_audio_upload_seconds is not None:
        row.max_audio_upload_seconds = int(payload.max_audio_upload_seconds)
    if payload.max_audio_upload_mb is not None:
        row.max_audio_upload_mb = float(payload.max_audio_upload_mb)

    await db.flush()
    return _row_to_out(row)
