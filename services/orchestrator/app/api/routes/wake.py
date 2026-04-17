"""Wake-word endpoints.

GET  /api/v1/wake/status            – current voice/session state
PATCH /api/v1/wake/settings         – update wake-word configuration
POST /api/v1/wake/activate          – trigger wake activation
POST /api/v1/wake/verify-and-unlock – run speaker verification + unlock session
POST /api/v1/wake/lock              – manually lock the session
POST /api/v1/voice/command          – session-gated command → planner/executor
"""

from __future__ import annotations

import base64

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.settings import UserSettings
from app.schemas.wake import (
    WakeMode,
    WakeSettings,
    WakeSettingsUpdate,
    WakeStatus,
    WakeActivateRequest,
    WakeVerifyRequest,
    WakeResponse,
    VoiceCommandRequest,
    VoiceCommandResponse,
    ContextResponse,
    VoiceState,
    SessionInfo,
)
from app.services import voice_session_service as vss
from app.services.voice_session_service import SessionExpiredError
from app.services.wake_word_service import check_wake_activation
from app.services.speaker_verification_service import verify_speaker
from app.services.audit_service import record_action
from app.services.task_planner import plan_command
from app.services.plan_executor import execute_plan
from app.services.command_router import _classify_with_llm
from app.tools.registry import get_tool
from app.schemas.plan import ExecutionPlan, PlanStep
from app.services.voice_shaper import (
    shape_for_voice,
    shape_approval_confirmation,
    is_interrupt_command,
)

router = APIRouter()


# ─── Helpers ──────────────────────────────────────────────────────────────────

async def _get_or_create_settings(db: AsyncSession) -> UserSettings:
    from sqlalchemy import select
    result = await db.execute(select(UserSettings).where(UserSettings.id == 1))
    row = result.scalar_one_or_none()
    if row is None:
        row = UserSettings(id=1)
        db.add(row)
        await db.flush()
    return row


def _wake_settings_from_row(row: UserSettings) -> WakeSettings:
    return WakeSettings(
        wake_word_enabled=bool(row.wake_word_enabled),
        primary_wake_phrase=row.primary_wake_phrase or "Lani",
        secondary_wake_phrase=row.secondary_wake_phrase or "Hey Lani",
        voice_session_timeout_seconds=int(row.voice_session_timeout_seconds if row.voice_session_timeout_seconds is not None else 0),
        require_reverification_after_timeout=bool(row.require_reverification_after_timeout),
        wake_mode=WakeMode(row.wake_mode or "manual"),
    )


def _build_status(row: UserSettings, session_info: SessionInfo, voice_state: VoiceState) -> WakeStatus:
    ws = _wake_settings_from_row(row)
    return WakeStatus(
        voice_state=voice_state,
        wake_mode=ws.wake_mode,
        wake_word_enabled=ws.wake_word_enabled,
        primary_wake_phrase=ws.primary_wake_phrase,
        secondary_wake_phrase=ws.secondary_wake_phrase,
        voice_session_timeout_seconds=ws.voice_session_timeout_seconds,
        require_reverification_after_timeout=ws.require_reverification_after_timeout,
        session=session_info,
        security_mode=row.security_mode or "disabled",
    )


async def _get_language(db: AsyncSession) -> str:
    """Return the configured assistant language (defaults to 'en')."""
    row = await _get_or_create_settings(db)
    lang = getattr(row, "assistant_language", None) or "en"
    # Normalise e.g. "en-US" → "en", "lt-LT" → "lt"
    return lang.split("-")[0].lower()


# ─── Routes ───────────────────────────────────────────────────────────────────

@router.get("/wake/status", response_model=WakeStatus, summary="Current wake/session state")
async def get_wake_status(db: AsyncSession = Depends(get_db)) -> WakeStatus:
    await vss.expire_if_needed(db)
    row = await _get_or_create_settings(db)
    return _build_status(row, vss.get_session().to_session_info(), vss.get_voice_state())


@router.patch("/wake/settings", response_model=WakeSettings, summary="Update wake-word config")
async def update_wake_settings(
    payload: WakeSettingsUpdate,
    db: AsyncSession = Depends(get_db),
) -> WakeSettings:
    row = await _get_or_create_settings(db)
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
        row.wake_mode = payload.wake_mode.value
    await db.flush()
    await record_action(db, "wake.settings.updated", "wake_word", "success")
    return _wake_settings_from_row(row)


@router.post("/wake/activate", response_model=WakeResponse, summary="Trigger wake activation")
async def wake_activate(
    body: WakeActivateRequest,
    db: AsyncSession = Depends(get_db),
) -> WakeResponse:
    """Trigger wake detection.

    In manual/push-to-talk mode this always succeeds if wake_word_enabled=True.
    In wake_phrase_placeholder mode the phrase_heard field is matched against
    the configured wake phrases (NOT real always-on detection).
    """
    await vss.expire_if_needed(db)
    row = await _get_or_create_settings(db)
    ws = _wake_settings_from_row(row)

    mode = body.mode_override or ws.wake_mode
    result = check_wake_activation(
        mode=mode,
        wake_word_enabled=ws.wake_word_enabled,
        primary_phrase=ws.primary_wake_phrase,
        secondary_phrase=ws.secondary_wake_phrase,
        phrase_heard=body.phrase_heard,
    )

    if not result["allowed"]:
        vss.set_voice_state(VoiceState.blocked)
        await record_action(
            db, "wake.activate", "wake_word", "blocked",
            result_summary=result["reason"],
        )
        return WakeResponse(
            ok=False,
            voice_state=VoiceState.blocked,
            session=vss.get_session().to_session_info(),
            message="Wake activation denied.",
            blocked_reason=result["reason"],
        )

    # If security mode requires verification, move to verifying state
    security_mode = row.security_mode or "disabled"
    if security_mode != "disabled" and bool(row.speaker_verification_enabled):
        vss.set_voice_state(VoiceState.verifying)
        await record_action(db, "wake.activate", "wake_word", "success",
                            result_summary="state=verifying, awaiting verification")
        return WakeResponse(
            ok=True,
            voice_state=VoiceState.verifying,
            session=vss.get_session().to_session_info(),
            message="Wake detected. Please verify your identity.",
        )

    # No verification required – unlock immediately
    session_info = await vss.unlock_session(
        db,
        timeout_seconds=ws.voice_session_timeout_seconds,
        require_reverification=ws.require_reverification_after_timeout,
    )
    await record_action(db, "wake.activate", "wake_word", "success",
                        result_summary="state=unlocked (no verification required)")
    return WakeResponse(
        ok=True,
        voice_state=VoiceState.unlocked,
        session=session_info,
        message="Wake detected. Session unlocked.",
    )


@router.post("/wake/verify-and-unlock", response_model=WakeResponse,
             summary="Run speaker verification and unlock session")
async def verify_and_unlock(
    body: WakeVerifyRequest,
    db: AsyncSession = Depends(get_db),
) -> WakeResponse:
    """Verify the speaker and, on success, unlock the voice session.

    If security_mode is 'disabled' and bypass=True, verification is skipped.
    """
    await vss.expire_if_needed(db)
    row = await _get_or_create_settings(db)
    ws = _wake_settings_from_row(row)

    security_mode = row.security_mode or "disabled"
    speaker_verification_enabled = bool(row.speaker_verification_enabled)

    # Bypass path – only when security is disabled
    if body.bypass:
        if security_mode != "disabled":
            await record_action(db, "wake.verify", "wake_word", "blocked",
                                result_summary="bypass attempted while security is active")
            return WakeResponse(
                ok=False,
                voice_state=VoiceState.blocked,
                session=vss.get_session().to_session_info(),
                message="Bypass not allowed while security mode is active.",
                blocked_reason="bypass_not_allowed",
            )
        session_info = await vss.unlock_session(
            db,
            timeout_seconds=ws.voice_session_timeout_seconds,
            require_reverification=ws.require_reverification_after_timeout,
        )
        return WakeResponse(
            ok=True,
            voice_state=VoiceState.unlocked,
            session=session_info,
            message="Session unlocked (no verification required).",
        )

    # Speaker verification path
    if not speaker_verification_enabled or security_mode == "disabled":
        # No verification configured – just unlock
        session_info = await vss.unlock_session(
            db,
            timeout_seconds=ws.voice_session_timeout_seconds,
            require_reverification=ws.require_reverification_after_timeout,
        )
        return WakeResponse(
            ok=True,
            voice_state=VoiceState.unlocked,
            session=session_info,
            message="Session unlocked (speaker verification not required).",
        )

    if not body.audio_base64:
        raise HTTPException(status_code=422, detail="audio_base64 required for speaker verification.")

    try:
        audio_bytes = base64.b64decode(body.audio_base64)
    except Exception:
        raise HTTPException(status_code=422, detail="audio_base64 is not valid base-64.")

    vss.set_voice_state(VoiceState.verifying)
    verification_result = await verify_speaker(db, audio_bytes)

    if verification_result.get("status") == "success":
        session_info = await vss.unlock_session(
            db,
            timeout_seconds=ws.voice_session_timeout_seconds,
            require_reverification=ws.require_reverification_after_timeout,
        )
        await record_action(db, "wake.verify", "wake_word", "success",
                            result_summary=f"session_id={session_info.session_id}")
        return WakeResponse(
            ok=True,
            voice_state=VoiceState.unlocked,
            session=session_info,
            message="Speaker verified. Session unlocked.",
        )
    else:
        vss.set_voice_state(VoiceState.blocked)
        reason = verification_result.get("reason", "verification_failed")
        await record_action(db, "wake.verify", "wake_word", "blocked",
                            result_summary=reason)
        return WakeResponse(
            ok=False,
            voice_state=VoiceState.blocked,
            session=vss.get_session().to_session_info(),
            message=verification_result.get("message", "Speaker verification failed."),
            blocked_reason=reason,
        )


@router.post("/wake/lock", response_model=WakeResponse, summary="Manually lock the voice session")
async def lock_session(db: AsyncSession = Depends(get_db)) -> WakeResponse:
    session_info = await vss.lock_session(db, reason="manual")
    return WakeResponse(
        ok=True,
        voice_state=VoiceState.idle,
        session=session_info,
        message="Voice session locked.",
    )


@router.get("/voice/context", response_model=ContextResponse, summary="Get current conversational context")
async def get_voice_context() -> ContextResponse:
    """Return recent conversational turns and last TTS text for context display / replay."""
    return ContextResponse(
        turns=vss.get_context_turns(),
        summary=vss.get_context_summary(),
        session_id=vss.get_session().to_session_info().session_id,
    )


@router.delete("/voice/context", summary="Clear conversational context")
async def clear_voice_context() -> dict:
    """Manually clear the conversational context (e.g. start a fresh topic)."""
    vss.clear_context()
    return {"ok": True}


# ─── Session-gated command execution ─────────────────────────────────────────

@router.post(
    "/voice/command",
    response_model=VoiceCommandResponse,
    summary="Submit a command through the active voice session",
)
async def voice_command(
    body: VoiceCommandRequest,
    db: AsyncSession = Depends(get_db),
) -> VoiceCommandResponse:
    """Execute a natural-language command only when the voice session is unlocked.

    Flow:
      1. Check session expiry (auto-lock if timed out).
      2. Reject with blocked_reason if not unlocked.
      3. Transition state: unlocked → processing.
      4. Route command through the planner → executor pipeline.
      5. Transition state: processing → responding.
      6. Optionally populate tts_text for the frontend TTS hook.
      7. Return structured VoiceCommandResponse.

    The session stays unlocked after the command completes so the user can
    issue follow-up commands without re-activating.
    """
    # 1. Enforce active session (auto-relock if expired, raise if locked)
    try:
        await vss.ensure_active_session(db)
    except SessionExpiredError as exc:
        blocked_reason = (
            "reverification_required" if exc.require_reverification else "session_expired"
        )
        msg = (
            "Voice session expired. Please verify again."
            if exc.require_reverification
            else "Voice session has expired. Please re-activate."
        )
        await record_action(
            db, "voice.command.rejected", "voice_session", "blocked",
            result_summary=blocked_reason,
        )
        return VoiceCommandResponse(
            ok=False,
            voice_state=VoiceState.timeout,
            session=vss.get_session().to_session_info(),
            command=body.command,
            overall_status="blocked",
            message=msg,
            blocked_reason=blocked_reason,
        )

    # 2. Reject if not unlocked (blocked/idle state)
    current_state = vss.get_voice_state()
    session_info = vss.get_session().to_session_info()
    if not session_info.unlocked:
        await record_action(
            db, "voice.command.rejected", "voice_session", "blocked",
            result_summary=f"state={current_state.value}",
        )
        return VoiceCommandResponse(
            ok=False,
            voice_state=current_state,
            session=session_info,
            command=body.command,
            overall_status="blocked",
            message="Voice session is locked. Activate Lani first.",
            blocked_reason="session_locked",
        )

    # 3. Interrupt detection – before anything else
    if is_interrupt_command(body.command):
        vss.set_voice_state(VoiceState.unlocked)
        await record_action(
            db, "voice.command.interrupted", "voice_session", "info",
            result_summary=f"interrupt={body.command[:40]}",
        )
        return VoiceCommandResponse(
            ok=True,
            voice_state=VoiceState.unlocked,
            session=vss.get_session().to_session_info(),
            command=body.command,
            overall_status="interrupted",
            message="Stopped.",
            tts_text=None,
            was_interrupt=True,
        )

    # 4. Processing state
    vss.set_voice_state(VoiceState.processing)
    await record_action(
        db, "voice.command.started", "voice_session", "info",
        result_summary=f"command={body.command[:80]}",
    )

    # 5. Planner → executor (inject context if requested)
    try:
        effective_command = body.command
        if body.include_context:
            ctx = vss.get_context_summary()
            if ctx:
                effective_command = f"{ctx}\nUser: {body.command}"

        plan = plan_command(effective_command)
        if plan is None:
            # No regex match — try LLM classifier, fall back to chat tool
            tool_name, params = await _classify_with_llm(effective_command, force_tool=True)
            if tool_name != "unknown":
                t = get_tool(tool_name)
                step = PlanStep(
                    index=0,
                    tool=tool_name,
                    description=f"Execute: {tool_name}",
                    args=params,
                    requires_approval=t.requires_approval if t else False,
                )
                plan = ExecutionPlan(goal=effective_command, steps=[step], is_multi_step=False)
            else:
                # Final fallback: treat as conversational chat
                step = PlanStep(
                    index=0,
                    tool="chat",
                    description="Conversational response",
                    args={"message": effective_command},
                    requires_approval=False,
                )
                plan = ExecutionPlan(goal=effective_command, steps=[step], is_multi_step=False)

        plan_result = await execute_plan(plan, db)

        # Determine language for TTS shaping
        lang = await _get_language(db)

        # 6. Approval-required gate
        if plan_result.overall_status == "approval_required":
            approval_tool = next(
                (r.tool for r in plan_result.step_results if r.status == "approval_required"),
                "unknown",
            )
            confirmation_prompt = shape_approval_confirmation(approval_tool, {}, lang)
            tts_text: str | None = confirmation_prompt if body.tts_response else None
            if tts_text:
                vss.set_last_tts(tts_text)

            vss.set_voice_state(VoiceState.waiting_for_confirmation)
            await record_action(
                db, "voice.command.approval_required", "voice_session", "info",
                result_summary=f"tool={approval_tool}",
            )
            vss.touch_session()
            return VoiceCommandResponse(
                ok=True,
                voice_state=VoiceState.waiting_for_confirmation,
                session=vss.get_session().to_session_info(),
                command=plan_result.command,
                overall_status=plan_result.overall_status,
                message=plan_result.message or "",
                step_results=[
                    {
                        "step_index": r.step_index,
                        "tool": r.tool,
                        "status": r.status,
                        "message": r.message,
                    }
                    for r in plan_result.step_results
                ],
                tts_text=tts_text,
                confirmation_prompt=confirmation_prompt,
            )

        # 7. Responding state
        vss.set_voice_state(VoiceState.speaking if body.tts_response else VoiceState.responding)

        # 8. Build shaped TTS text
        tts_text = None
        if body.tts_response:
            raw_msg = plan_result.message or ("Done." if plan_result.overall_status == "completed" else "That failed.")
            tts_text = shape_for_voice(raw_msg, language=lang)
            vss.set_last_tts(tts_text)

        await record_action(
            db, "voice.command.completed", "voice_session", "success",
            result_summary=f"status={plan_result.overall_status}",
        )

        # 9. Record context turns for follow-up
        vss.add_context_turn("user", body.command)
        vss.add_context_turn("assistant", plan_result.message or "Done.")

        # Update last_activity_at so expiry clock resets from this command
        vss.touch_session()

        # Transition back to unlocked so follow-up commands work
        vss.set_voice_state(VoiceState.unlocked)

        return VoiceCommandResponse(
            ok=True,
            voice_state=VoiceState.unlocked,
            session=vss.get_session().to_session_info(),
            command=plan_result.command,
            overall_status=plan_result.overall_status,
            message=plan_result.message or "",
            step_results=[
                {
                    "step_index": r.step_index,
                    "tool": r.tool,
                    "status": r.status,
                    "message": r.message,
                }
                for r in plan_result.step_results
            ],
            tts_text=tts_text,
            context_turns=vss.get_context_turns(),
        )

    except Exception as exc:
        vss.set_voice_state(VoiceState.unlocked)
        await record_action(
            db, "voice.command.error", "voice_session", "error",
            result_summary=str(exc)[:200],
        )
        return VoiceCommandResponse(
            ok=False,
            voice_state=VoiceState.unlocked,
            session=vss.get_session().to_session_info(),
            command=body.command,
            overall_status="error",
            message=f"Command failed: {exc}",
        )
