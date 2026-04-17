"""
Voice route – STT transcription and TTS synthesis endpoints.

Both endpoints are designed to work with the placeholder provider out of the
box.  They return ``status: "provider_not_configured"`` until a real provider
is wired up in ``app/services/voice_service.py``.

Transcription endpoint
----------------------
Accepts multipart/form-data with:
  - ``audio``    (UploadFile) – raw audio captured from the browser
  - ``language`` (Form, optional) – BCP-47 tag, default "en"

Synthesis endpoint
------------------
Accepts JSON body matching ``SynthesizeRequest``.
Returns JSON with optional ``audio_base64`` field (base-64 encoded audio).
"""

from __future__ import annotations

import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

from fastapi import APIRouter, Form, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.settings import UserSettings
from app.models.voice_profile import VoiceProfile
from app.schemas.voice import (
    EnrollFinishResponse,
    EnrollSampleResponse,
    EnrollStartResponse,
    SynthesizeRequest,
    SynthesizeResponse,
    TranscribeResponse,
    VerifyResponse,
    VoiceProfileOut,
)
from app.services.voice_service import (
    list_providers,
    synthesize_speech,
    transcribe_audio,
)
from app.services.voice_profile_service import (
    start_enrollment,
    add_enrollment_sample,
    finish_enrollment,
    get_voice_profile,
    delete_voice_profile,
)
from app.services.speaker_verification_service import verify_speaker
from app.services.audit_service import record_action
from fastapi import Depends

router = APIRouter()

# ─── Helpers ──────────────────────────────────────────────────────────────────


async def _record_voice_action(
    db: AsyncSession,
    command: str,
    status: str,
    result_summary: str,
) -> None:
    await record_action(db, command, "voice", status, result_summary=result_summary)


async def _reject_voice_action(
    db: AsyncSession,
    command: str,
    result_summary: str,
    *,
    status_code: int,
    detail: str,
) -> None:
    await _record_voice_action(db, command, "error", result_summary)
    raise HTTPException(status_code=status_code, detail=detail)


async def _read_audio_bytes(audio: UploadFile) -> bytes:
    return await audio.read()


async def _record_voice_completion(
    db: AsyncSession,
    command: str,
    status: str,
    summary: str,
) -> None:
    await _record_voice_action(db, command, status, summary)


def _serialize_voice_profile(profile: VoiceProfile) -> VoiceProfileOut:
    return VoiceProfileOut(
        id=profile.id,
        profile_name=profile.profile_name,
        owner_label=profile.owner_label,
        enrollment_status=profile.enrollment_status,
        sample_count=profile.sample_count,
        verification_enabled=profile.verification_enabled,
        last_verified_at=(
            profile.last_verified_at.isoformat() if profile.last_verified_at else None
        ),
        version=profile.version,
    )

async def _get_settings(db: AsyncSession) -> UserSettings:
    """Return the persisted settings row (creates it if absent)."""
    result = await db.execute(select(UserSettings).where(UserSettings.id == 1))
    row = result.scalar_one_or_none()
    if row is None:
        row = UserSettings(id=1)
        db.add(row)
        await db.flush()
    return row


# ─── Transcription (STT) ──────────────────────────────────────────────────────

@router.post(
    "/voice/transcribe",
    response_model=TranscribeResponse,
    summary="Transcribe audio to text",
    description=(
        "Submit audio captured from the microphone. "
        "Returns a transcript and provider info. "
        "When no provider is configured the response contains "
        "status='provider_not_configured' and setup instructions."
    ),
)
async def transcribe(
    audio: UploadFile = File(
        ...,
        description="Raw audio file (WebM, WAV, MP3, …) from the browser MediaRecorder",
    ),
    language: str = Form(
        default="en",
        description="BCP-47 language tag for the audio",
    ),
    db: AsyncSession = Depends(get_db),
) -> TranscribeResponse:
    """
    Accept a recorded audio upload, validate it, transcribe it, and return
    a structured response with transcript, detected_language, duration_ms,
    and provider_status.

    Errors:
      - 422  STT disabled in settings
      - 422  Empty file
      - 413  File exceeds configured size limit
    """
    settings_row = await _get_settings(db)

    # ── 1. Check STT enabled ───────────────────────────────────────────────
    stt_enabled: bool = getattr(settings_row, "stt_enabled", True)
    if not stt_enabled:
        await _reject_voice_action(
            db,
            "voice.transcribe.rejected",
            "stt_disabled",
            status_code=422,
            detail="Speech-to-text is disabled. Enable it in Settings → STT.",
        )

    # ── 2. Validate size ───────────────────────────────────────────────────
    max_mb: float = float(getattr(settings_row, "max_audio_upload_mb", 25) or 25)
    max_bytes = int(max_mb * 1024 * 1024)

    # UploadFile.size may be None; fall through to post-read check
    if audio.size is not None and audio.size > max_bytes:
        await _reject_voice_action(
            db,
            "voice.transcribe.rejected",
            f"file_too_large:{audio.size}",
            status_code=413,
            detail=f"Audio file exceeds {max_mb:.0f} MB limit.",
        )

    audio_bytes = await _read_audio_bytes(audio)
    if not audio_bytes:
        await _reject_voice_action(
            db,
            "voice.transcribe.rejected",
            "empty_file",
            status_code=422,
            detail="Empty audio file received.",
        )

    # Post-read size check (for uploads where size header is missing)
    if len(audio_bytes) > max_bytes:
        await _reject_voice_action(
            db,
            "voice.transcribe.rejected",
            f"file_too_large:{len(audio_bytes)}",
            status_code=413,
            detail=f"Audio file exceeds {max_mb:.0f} MB limit.",
        )

    # ── 3. Log attempt ─────────────────────────────────────────────────────
    await _record_voice_action(
        db,
        "voice.transcribe.attempt",
        "pending",
        f"bytes={len(audio_bytes)},language={language}",
    )

    # ── 3b. Speaker verification (jei yra enrolled profilis) ───────────────
    verification = await verify_speaker(db, audio_bytes)
    if verification["status"] == "blocked":
        await _record_voice_action(
            db,
            "voice.transcribe.rejected",
            "error",
            f"speaker_blocked:similarity={verification.get('similarity', 0):.3f}",
        )
        # Grąžiname TranscribeResponse su status=error ir aiškiu pranešimu
        from app.schemas.voice import TranscribeResponse as TR
        return TR(
            status="error",
            transcript="",
            provider="speaker_verification",
            provider_status="blocked",
            detected_language=language,
            duration_ms=0,
            message=verification["message"],
        )
    if verification["status"] in {"unavailable", "error"}:
        logger.warning(
            "Speaker verification unavailable/error during transcribe: %s",
            verification.get("message"),
        )

    # ── 4. Transcribe ──────────────────────────────────────────────────────
    try:
        result = await transcribe_audio(audio_bytes, language)
    except Exception as exc:
        import traceback
        logger.error("Transcription exception: %s\n%s", exc, traceback.format_exc())
        logger.error("Audio bytes=%d, first16=%s", len(audio_bytes), audio_bytes[:16].hex())
        await _record_voice_action(db, "voice.transcribe.error", "error", str(exc)[:200])
        provider_name = (
            getattr(settings_row, "stt_provider", "")
            or getattr(settings_row, "tts_provider", "")
            or "openai"
        )
        return TranscribeResponse(
            status="error",
            transcript="",
            provider=provider_name,
            provider_status="error",
            detected_language=language,
            duration_ms=0,
            message=f"Transcription failed: {exc}",
        )

    # ── 5. Log outcome ─────────────────────────────────────────────────────
    outcome = result.status  # "success" | "provider_not_configured" | "error"
    logger.info("Transcript: %r (chars=%d)", result.transcript, len(result.transcript))
    await _record_voice_completion(
        db,
        "voice.transcribe.done",
        outcome,
        (
            f"provider={result.provider},chars={len(result.transcript)},"
            f"lang={result.detected_language or language}"
        ),
    )

    return result


# ─── Synthesis (TTS) ──────────────────────────────────────────────────────────

@router.post(
    "/voice/synthesize",
    response_model=SynthesizeResponse,
    summary="Synthesize text to speech",
    description=(
        "Submit text and receive base-64 encoded audio. "
        "When no provider is configured the response contains "
        "status='provider_not_configured' and setup instructions."
    ),
)
async def synthesize(
    body: SynthesizeRequest,
    db: AsyncSession = Depends(get_db),
) -> SynthesizeResponse:
    """
    Validate, synthesize, audit-log, and return audio for the given text.

    Errors:
      - 422  TTS disabled in settings
      - 422  Empty or too-long text
    """
    settings_row = await _get_settings(db)

    # ── 1. Check TTS enabled ───────────────────────────────────────────────
    tts_enabled: bool = bool(getattr(settings_row, "tts_enabled", True))
    if not tts_enabled:
        await _reject_voice_action(
            db,
            "voice.tts.rejected",
            "tts_disabled",
            status_code=422,
            detail="Text-to-speech is disabled. Enable it in Settings → TTS.",
        )

    # ── 2. Validate text ───────────────────────────────────────────────────
    if not body.text.strip():
        await _reject_voice_action(
            db,
            "voice.tts.rejected",
            "empty_text",
            status_code=422,
            detail="text must not be empty.",
        )
    if len(body.text) > 5000:
        await _reject_voice_action(
            db,
            "voice.tts.rejected",
            f"text_too_long:{len(body.text)}",
            status_code=422,
            detail="text exceeds 5 000 character limit for synthesis.",
        )

    # ── 3. Log attempt ─────────────────────────────────────────────────────
    await _record_voice_action(
        db,
        "voice.tts.attempt",
        "pending",
        f"chars={len(body.text)},voice={body.voice},language={body.language}",
    )

    # ── 4. Synthesize ──────────────────────────────────────────────────────
    import time as _time
    _t0 = _time.monotonic()
    try:
        result = await synthesize_speech(body.text, body.voice, body.language)
    except Exception as exc:
        await _record_voice_action(db, "voice.tts.error", "error", str(exc)[:200])
        raise HTTPException(status_code=502, detail=f"Synthesis failed: {exc}") from exc
    _elapsed_ms = int((_time.monotonic() - _t0) * 1000)
    logger.info("TTS: %r → %dms (model=tts-1, lang=%s)", body.text[:60], _elapsed_ms, body.language)

    # ── 5. Log outcome ─────────────────────────────────────────────────────
    outcome = result.status
    await _record_voice_completion(
        db,
        "voice.tts.done",
        outcome,
        (
            f"provider={result.provider},"
            f"has_audio={result.audio_base64 is not None},"
            f"provider_status={result.provider_status}"
        ),
    )

    return result


# ─── Provider info ────────────────────────────────────────────────────────────

@router.get(
    "/voice/providers",
    summary="List registered voice providers",
)
async def providers() -> JSONResponse:
    """Return metadata about all registered STT/TTS providers."""
    data = await list_providers()
    return JSONResponse(content=data)


# ─── Voice profile enrollment & verification (placeholder-first implementation)

class EnrollStartRequest(BaseModel):
    profile_name: str = "Primary"


@router.post("/voice/enroll/start")
async def enroll_start(
    body: EnrollStartRequest,
    db: AsyncSession = Depends(get_db),
) -> EnrollStartResponse:
    """Start an enrollment session and create a profile record."""
    profile = await start_enrollment(db, profile_name=body.profile_name)
    await _record_voice_action(db, "voice.enroll.start", "success", f"profile_id={profile.id}")
    return EnrollStartResponse(
        status="ok",
        profile_id=profile.id,
        enrollment_status=profile.enrollment_status,
    )


@router.post("/voice/enroll/sample")
async def enroll_sample(
    audio: UploadFile = File(...),
    profile_id: int = Form(...),
    db: AsyncSession = Depends(get_db),
) -> EnrollSampleResponse:
    """Upload one enrollment sample for the given profile."""
    audio_bytes = await _read_audio_bytes(audio)
    if not audio_bytes:
        await _reject_voice_action(
            db,
            "voice.enroll.sample.rejected",
            "empty_file",
            status_code=422,
            detail="Empty audio file received.",
        )
    sample_path = await add_enrollment_sample(db, profile_id, audio_bytes)
    await _record_voice_action(db, "voice.enroll.sample", "success", f"profile_id={profile_id}")
    return EnrollSampleResponse(status="ok", sample_path=sample_path)


@router.post("/voice/enroll/finish")
async def enroll_finish(
    profile_id: int = Form(...),
    db: AsyncSession = Depends(get_db),
) -> EnrollFinishResponse:
    """Complete enrollment – mark profile enrolled when enough samples provided."""
    try:
        profile = await finish_enrollment(db, profile_id)
    except RuntimeError as exc:
        await _record_voice_action(
            db,
            "voice.enroll.finish",
            "error",
            f"profile_id={profile_id},reason={exc}",
        )
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    await _record_voice_action(
        db,
        "voice.enroll.finish",
        "success",
        f"profile_id={profile.id},status={profile.enrollment_status}",
    )
    return EnrollFinishResponse(
        status="ok",
        enrollment_status=profile.enrollment_status,
        sample_count=profile.sample_count,
    )


@router.get("/voice/profile")
async def voice_profile(db: AsyncSession = Depends(get_db)):
    """Return current voice profile metadata (or null)."""
    profile = await get_voice_profile(db)
    if not profile:
        return {"profile": None}
    return {"profile": _serialize_voice_profile(profile).model_dump()}


@router.delete("/voice/profile")
async def delete_profile(db: AsyncSession = Depends(get_db)):
    await delete_voice_profile(db)
    await _record_voice_action(db, "voice.profile.delete", "success", "deleted")
    return {"status": "ok"}


@router.post("/voice/verify")
async def verify(
    audio: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> VerifyResponse:
    audio_bytes = await _read_audio_bytes(audio)
    if not audio_bytes:
        await _reject_voice_action(
            db,
            "voice.verify.rejected",
            "empty_file",
            status_code=422,
            detail="Empty audio file received.",
        )
    result = await verify_speaker(db, audio_bytes)
    await _record_voice_action(
        db,
        "voice.verify",
        result.get("status", "error"),
        result.get("reason") or result.get("message") or "",
    )
    return VerifyResponse(**result)
