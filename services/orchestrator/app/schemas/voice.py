"""Pydantic schemas for the voice (STT / TTS) layer."""

from typing import Literal, Optional
from pydantic import BaseModel


# ─── STT (Speech-to-Text / Transcription) ────────────────────────────────────

class TranscribeRequest(BaseModel):
    """
    Metadata that accompanies the audio upload.

    The raw audio bytes are sent as multipart/form-data; this schema
    represents the accompanying JSON fields.
    """
    language: str = "en"
    """BCP-47 language tag for the audio (e.g. 'en', 'fr', 'de')."""


class TranscribeResponse(BaseModel):
    """Result of a transcription attempt."""
    transcript: str
    """The recognised text, or an empty string when nothing was heard."""

    confidence: float | None = None
    """Provider-supplied confidence score in [0, 1]. None when unavailable."""

    provider: str
    """Name of the STT provider that processed the audio (or 'placeholder')."""

    status: Literal["success", "error", "provider_not_configured"]
    """Machine-readable outcome code."""

    message: str | None = None
    """Human-readable note (e.g. setup instructions when provider not configured)."""

    # ── Extended fields populated when available ─────────────────────────────
    detected_language: Optional[str] = None
    """BCP-47 language code detected by the provider (e.g. 'en', 'fr').
    None when provider does not support language detection."""

    duration_ms: Optional[int] = None
    """Duration of the submitted audio in milliseconds, if measurable."""

    provider_status: str = "not_configured"
    """Human-readable provider readiness: 'configured' | 'not_configured' | 'error'."""


# ─── TTS (Text-to-Speech / Synthesis) ────────────────────────────────────────

class SynthesizeRequest(BaseModel):
    """Parameters for a speech synthesis request."""
    text: str
    """The text to speak. Keep it under 5 000 characters for most providers."""

    voice: str = "default"
    """Provider-specific voice identifier (e.g. 'alloy', 'nova', 'en-US-JennyNeural')."""

    language: str = "en"
    """BCP-47 language tag."""


class SynthesizeResponse(BaseModel):
    """Result of a speech synthesis attempt."""
    audio_base64: str | None = None
    """Base-64 encoded MP3/WAV bytes. None when provider is not configured."""

    mime_type: str = "audio/mpeg"
    """MIME type of the audio data (e.g. 'audio/mpeg', 'audio/wav')."""

    provider: str
    """Name of the TTS provider (or 'placeholder')."""

    status: Literal["success", "error", "provider_not_configured"]
    message: str | None = None

    # ── Extended fields populated when available ─────────────────────────────
    duration_ms: Optional[int] = None
    """Duration of the generated audio in milliseconds, if measurable."""

    provider_status: str = "not_configured"
    """Human-readable provider readiness: 'configured' | 'not_configured' | 'error'."""


# ─── Provider capability info ─────────────────────────────────────────────────

class VoiceProviderInfo(BaseModel):
    """Describes a registered voice provider."""
    name: str
    stt_available: bool
    tts_available: bool
    requires_api_key: bool
    configured: bool
    """True when the required API key / credentials are present."""


# ─── Enrollment / verification schemas ──────────────────────────────────────


class EnrollStartResponse(BaseModel):
    status: str
    profile_id: int | None = None
    enrollment_status: str | None = None


class EnrollSampleResponse(BaseModel):
    status: str
    sample_path: str | None = None


class EnrollFinishResponse(BaseModel):
    status: str
    enrollment_status: str | None = None
    sample_count: int | None = None


class VoiceProfileOut(BaseModel):
    id: int
    profile_name: str
    owner_label: str
    enrollment_status: str
    sample_count: int
    verification_enabled: bool
    last_verified_at: str | None = None
    version: int


class VerifyResponse(BaseModel):
    status: str
    reason: str | None = None
    message: str | None = None
