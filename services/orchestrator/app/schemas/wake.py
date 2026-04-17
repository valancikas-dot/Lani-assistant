"""Pydantic schemas for wake-word and voice-session state."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ─── Enums ────────────────────────────────────────────────────────────────────

class VoiceState(str, Enum):
    """Current state of the voice pipeline."""
    idle = "idle"
    wake_detected = "wake_detected"
    listening = "listening"
    verifying = "verifying"
    unlocked = "unlocked"
    processing = "processing"
    responding = "responding"
    speaking = "speaking"
    waiting_for_confirmation = "waiting_for_confirmation"
    blocked = "blocked"
    timeout = "timeout"


class WakeMode(str, Enum):
    """How wake activation is triggered.

    manual               – user explicitly presses a button (no passive listening)
    push_to_talk         – user holds a key/button
    wake_phrase_placeholder – keyword match against STT transcript (not true always-on)
    keyword_live         – always-on browser SpeechRecognition listener (frontend-driven)
    provider_ready       – a real always-on wake-word provider is wired up
    """
    manual = "manual"
    push_to_talk = "push_to_talk"
    wake_phrase_placeholder = "wake_phrase_placeholder"
    keyword_live = "keyword_live"
    provider_ready = "provider_ready"


# ─── Settings ─────────────────────────────────────────────────────────────────

class WakeSettings(BaseModel):
    wake_word_enabled: bool = False
    primary_wake_phrase: str = "Lani"
    secondary_wake_phrase: str = "Hey Lani"
    voice_session_timeout_seconds: int = Field(default=0, ge=0, le=86400)
    require_reverification_after_timeout: bool = False
    wake_mode: WakeMode = WakeMode.manual


class WakeSettingsUpdate(BaseModel):
    wake_word_enabled: Optional[bool] = None
    primary_wake_phrase: Optional[str] = None
    secondary_wake_phrase: Optional[str] = None
    voice_session_timeout_seconds: Optional[int] = Field(default=None, ge=0, le=86400)
    require_reverification_after_timeout: Optional[bool] = None
    wake_mode: Optional[WakeMode] = None


# ─── Status ───────────────────────────────────────────────────────────────────

class SessionInfo(BaseModel):
    unlocked: bool = False
    unlocked_at: Optional[str] = None        # ISO timestamp (naive UTC)
    expires_at: Optional[str] = None         # ISO timestamp (naive UTC)
    seconds_remaining: Optional[int] = None
    session_id: Optional[str] = None
    last_activity_at: Optional[str] = None   # ISO timestamp; updated on each command


class WakeStatus(BaseModel):
    voice_state: VoiceState
    wake_mode: WakeMode
    wake_word_enabled: bool
    primary_wake_phrase: str
    secondary_wake_phrase: str
    voice_session_timeout_seconds: int
    require_reverification_after_timeout: bool
    session: SessionInfo
    # Security context – lets the frontend know what mode is active
    security_mode: str = "disabled"


# ─── Requests ─────────────────────────────────────────────────────────────────

class WakeActivateRequest(BaseModel):
    """Trigger wake activation (manual / push-to-talk / phrase-match mode)."""
    phrase_heard: Optional[str] = Field(
        default=None,
        description="Phrase heard – used in wake_phrase_placeholder mode to validate keyword match.",
    )
    mode_override: Optional[WakeMode] = Field(
        default=None,
        description="Override active wake mode for this request only.",
    )


class WakeVerifyRequest(BaseModel):
    """Submit audio or bypass token to attempt voice-session unlock."""
    audio_base64: Optional[str] = Field(
        default=None,
        description="Base-64-encoded audio to run speaker verification against.",
    )
    bypass: bool = Field(
        default=False,
        description="Skip verification check – only valid when security_mode=='disabled'.",
    )


class VoiceCommandRequest(BaseModel):
    """Submit a text command through the active voice session.

    The backend validates the session is unlocked before routing the command
    to the planner/executor pipeline.  The ``command`` field is the same
    natural-language string accepted by POST /api/v1/plans.
    """
    command: str = Field(..., description="Natural-language command to execute.")
    tts_response: bool = Field(
        default=False,
        description="If True, the response will include a TTS-ready text payload.",
    )
    include_context: bool = Field(
        default=True,
        description="If True, prepend recent conversational turns to the planner prompt.",
    )


# ─── Responses ────────────────────────────────────────────────────────────────

class WakeResponse(BaseModel):
    ok: bool
    voice_state: VoiceState
    session: SessionInfo
    message: str = ""
    blocked_reason: Optional[str] = None


class VoiceCommandResponse(BaseModel):
    """Response from a session-gated voice command."""
    ok: bool
    voice_state: VoiceState
    session: SessionInfo
    # Planner/executor result summary
    command: str
    overall_status: str
    message: str
    step_results: List[Dict[str, Any]] = Field(default_factory=list)
    # TTS hook – populated only when tts_response=True
    tts_text: Optional[str] = None
    # Populated if session was blocked/expired
    blocked_reason: Optional[str] = None
    # Set True when the command was detected as a voice interrupt
    was_interrupt: bool = False
    # Confirmation prompt spoken before approval gate
    confirmation_prompt: Optional[str] = None
    # Recent context turns (last 3 pairs) for frontend display
    context_turns: List[Dict[str, str]] = Field(default_factory=list)


class ContextResponse(BaseModel):
    """Response from GET /voice/context."""
    turns: List[Dict[str, str]]
    summary: str
    session_id: Optional[str] = None
