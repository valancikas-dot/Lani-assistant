"""
Voice Confirmation Loop – interruptible, real-time voice approval flow.

This module extends the existing voice infrastructure with a
"confirmation channel": before any HIGH or CRITICAL action executes,
Lani can prompt the user via TTS and listen for a spoken response.

Flow
────
1. Caller invokes ``request_voice_confirmation(prompt, approval_id, db)``
2. Module synthesises the prompt (TTS) and stores a ``ConfirmationRequest``
3. Client polls  GET /api/v1/voice/confirmation/{cid}  for status
4. Client POSTs  /api/v1/voice/confirmation/{cid}/respond  with audio or text
5. Module classifies the response:
     yes/confirm/approve  → "approved"
     no/stop/deny/cancel  → "denied"
     modify/change        → "modify"  (returns request for clarification)
6. approval_service.resolve() is called automatically on approved/denied

Interrupt commands
──────────────────
  "yes" / "approve" / "go ahead"  → approve
  "no"  / "stop"    / "cancel"    → deny
  "modify" / "change"             → request modification
  "pause" / "wait"                → hold (keeps request open)

In-process store (no DB) – confirmation requests are short-lived (<60 s).
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import secrets
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────
CONFIRMATION_TTL_SECONDS = 120

# Keyword → verdict mapping (checked against lowercased response text)
_APPROVE_KEYWORDS = {"yes", "yep", "yeah", "approve", "confirmed", "confirm",
                     "go", "proceed", "do it", "go ahead", "ok", "okay"}
_DENY_KEYWORDS    = {"no", "nope", "stop", "cancel", "deny", "don't", "abort",
                     "wait", "hold", "pause", "never"}
_MODIFY_KEYWORDS  = {"modify", "change", "edit", "update", "different", "instead",
                     "actually", "revise"}


# ─── Data model ───────────────────────────────────────────────────────────────

@dataclass
class ConfirmationRequest:
    confirmation_id: str
    prompt: str
    approval_id: Optional[int]        # linked ApprovalRequest DB row
    action: str                        # tool name being confirmed
    risk_level: str = "high"
    status: str = "pending"            # pending | approved | denied | expired | modify
    response_text: Optional[str] = None
    created_at: datetime.datetime = field(default_factory=datetime.datetime.utcnow)
    expires_at: datetime.datetime = field(
        default_factory=lambda: datetime.datetime.utcnow()
        + datetime.timedelta(seconds=CONFIRMATION_TTL_SECONDS)
    )
    tts_audio_base64: Optional[str] = None   # pre-synthesised prompt audio

    def is_expired(self) -> bool:
        return datetime.datetime.utcnow() > self.expires_at

    def to_dict(self) -> Dict[str, Any]:
        return {
            "confirmation_id": self.confirmation_id,
            "prompt": self.prompt,
            "approval_id": self.approval_id,
            "action": self.action,
            "risk_level": self.risk_level,
            "status": self.status,
            "response_text": self.response_text,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "has_audio": self.tts_audio_base64 is not None,
        }


# ─── In-process store ─────────────────────────────────────────────────────────

_pending: Dict[str, ConfirmationRequest] = {}
_callbacks: Dict[str, List[Callable]] = {}


# ─── Core functions ───────────────────────────────────────────────────────────

async def request_voice_confirmation(
    prompt: str,
    action: str,
    approval_id: Optional[int] = None,
    risk_level: str = "high",
    synthesise_tts: bool = True,
) -> ConfirmationRequest:
    """
    Create a confirmation request and optionally pre-synthesise the TTS prompt.

    Returns the ConfirmationRequest immediately; resolution is async via respond().
    """
    cid = secrets.token_hex(12)
    req = ConfirmationRequest(
        confirmation_id=cid,
        prompt=prompt,
        approval_id=approval_id,
        action=action,
        risk_level=risk_level,
    )

    if synthesise_tts:
        try:
            from app.services.voice_service import _get_provider
            vs = _get_provider()
            synth = await vs.synthesize(text=prompt, voice="alloy", language="en")
            req.tts_audio_base64 = synth.audio_base64
        except Exception as exc:
            log.warning("[voice_confirm] TTS synthesis failed: %s", exc)

    _pending[cid] = req
    log.info("[voice_confirm] created confirmation %s for action=%s", cid, action)
    return req


def classify_response(text: str) -> str:
    """
    Map a free-text spoken/typed response to a verdict string.

    Returns: "approved" | "denied" | "modify" | "unknown"
    """
    words = set(text.lower().replace(",", " ").replace(".", " ").split())

    if words & _APPROVE_KEYWORDS:
        return "approved"
    if words & _DENY_KEYWORDS:
        return "denied"
    if words & _MODIFY_KEYWORDS:
        return "modify"
    return "unknown"


async def respond(
    confirmation_id: str,
    response_text: str,
    db: Any = None,
) -> Optional[ConfirmationRequest]:
    """
    Process a user response (text or transcript) for a pending confirmation.

    Automatically resolves the linked ApprovalRequest if db is provided.
    """
    req = _pending.get(confirmation_id)
    if req is None:
        return None

    if req.is_expired():
        req.status = "expired"
        _pending.pop(confirmation_id, None)
        return req

    verdict = classify_response(response_text)
    req.response_text = response_text

    if verdict == "approved":
        req.status = "approved"
        if req.approval_id and db is not None:
            try:
                from app.services.approval_service import resolve
                await resolve(db, req.approval_id, "approved")
                log.info("[voice_confirm] auto-approved approval_id=%d", req.approval_id)
            except Exception as exc:
                log.error("[voice_confirm] approval resolve failed: %s", exc)

    elif verdict == "denied":
        req.status = "denied"
        if req.approval_id and db is not None:
            try:
                from app.services.approval_service import resolve
                await resolve(db, req.approval_id, "denied")
                log.info("[voice_confirm] auto-denied approval_id=%d", req.approval_id)
            except Exception as exc:
                log.error("[voice_confirm] approval resolve failed: %s", exc)

    elif verdict == "modify":
        req.status = "modify"

    else:
        # Unknown response – keep pending, ask again
        log.info("[voice_confirm] unknown response '%s' for %s – keeping pending", response_text, confirmation_id)
        return req

    # Fire callbacks
    for cb in _callbacks.get(confirmation_id, []):
        try:
            if asyncio.iscoroutinefunction(cb):
                await cb(req)
            else:
                cb(req)
        except Exception as exc:
            log.error("[voice_confirm] callback error: %s", exc)

    if req.status in ("approved", "denied"):
        _pending.pop(confirmation_id, None)

    return req


def get_confirmation(confirmation_id: str) -> Optional[ConfirmationRequest]:
    """Retrieve a pending confirmation by ID."""
    req = _pending.get(confirmation_id)
    if req and req.is_expired():
        req.status = "expired"
        _pending.pop(confirmation_id, None)
    return req


def list_pending_confirmations() -> List[Dict[str, Any]]:
    """Return all non-expired pending confirmations as dicts."""
    expired = [cid for cid, r in _pending.items() if r.is_expired()]
    for cid in expired:
        _pending[cid].status = "expired"
        _pending.pop(cid)
    return [r.to_dict() for r in _pending.values()]


def register_callback(confirmation_id: str, cb: Callable) -> None:
    """Register a callback to be fired when a confirmation is resolved."""
    _callbacks.setdefault(confirmation_id, []).append(cb)


def build_confirmation_prompt(action: str, params: Dict[str, Any], risk_level: str) -> str:
    """
    Generate a natural-language TTS-friendly confirmation prompt.
    """
    param_summary = ", ".join(
        f"{k}: {str(v)[:60]}" for k, v in list(params.items())[:3]
    )
    risk_phrase = {
        "high": "This is a high-risk action.",
        "critical": "Warning: this is a critical action that cannot be undone.",
        "medium": "Please confirm.",
    }.get(risk_level, "Please confirm.")

    return (
        f"I am about to perform: {action.replace('_', ' ')}. "
        f"{param_summary}. "
        f"{risk_phrase} "
        f"Say yes to approve, or no to cancel."
    )


# ─── Retry-once logic ─────────────────────────────────────────────────────────

# Tracks how many unclear responses each confirmation has received
_unclear_count: Dict[str, int] = {}

_RETRY_PROMPT_SUFFIX = " I didn't understand. Please say yes to approve or no to cancel."


async def respond_with_retry(
    confirmation_id: str,
    response_text: str,
    db: Any = None,
    *,
    speaker_verified: bool = False,
) -> Optional[ConfirmationRequest]:
    """
    Wrapper around ``respond()`` that gives the user exactly one retry if the
    first response is unrecognised, then falls back to the manual approval UI.

    In **strict** security mode, any high- or critical-risk confirmation
    additionally requires ``speaker_verified=True``.  If the speaker cannot be
    verified the confirmation is routed to the manual approval UI immediately,
    preserving the linked ApprovalRequest in ``pending`` status.
    """
    req = _pending.get(confirmation_id)
    if req is None:
        return None

    # Check expiry first
    if req.is_expired():
        return await _expire_to_manual(req, db)

    # ── Strict-mode speaker verification gate ─────────────────────────────────
    if req.risk_level in ("high", "critical") and not speaker_verified:
        # Load security_mode from DB settings (best-effort; default = normal)
        _security_mode = "normal"
        if db is not None:
            try:
                from sqlalchemy import select
                from app.models.settings import UserSettings
                _sr = await db.execute(select(UserSettings).where(UserSettings.id == 1))
                _settings = _sr.scalar_one_or_none()
                if _settings is not None:
                    _security_mode = getattr(_settings, "security_mode", "normal") or "normal"
            except Exception as _exc:
                log.warning("[voice_confirm] could not load security_mode: %s", _exc)

        if _security_mode == "strict":
            log.warning(
                "[voice_confirm] strict mode: speaker not verified for %s (action=%s risk=%s) "
                "– routing to manual approval",
                confirmation_id, req.action, req.risk_level,
            )
            if db is not None and req.approval_id is not None:
                try:
                    from app.services.audit_service import record_action
                    await record_action(
                        db,
                        req.action,
                        req.action,
                        "voice_speaker_unverified",
                        (
                            f"Voice confirmation {confirmation_id} rejected: strict mode "
                            f"requires speaker verification for {req.risk_level}-risk action "
                            f"'{req.action}'. Approval #{req.approval_id} remains pending."
                        ),
                    )
                except Exception as _ae:
                    log.warning("[voice_confirm] audit log failed on speaker check: %s", _ae)
            return await _expire_to_manual(req, db)

    verdict = classify_response(response_text)

    if verdict != "unknown":
        # Clear retry counter and process normally
        _unclear_count.pop(confirmation_id, None)
        return await respond(confirmation_id, response_text, db)

    # Unknown response
    attempt = _unclear_count.get(confirmation_id, 0) + 1
    _unclear_count[confirmation_id] = attempt

    if attempt == 1:
        # First unclear response → ask again via TTS
        log.info(
            "[voice_confirm] unclear response (attempt 1) for %s – retrying",
            confirmation_id,
        )
        retry_prompt = req.prompt + _RETRY_PROMPT_SUFFIX
        try:
            from app.services.voice_service import _get_provider
            vs = _get_provider()
            synth = await vs.synthesize(text=retry_prompt, voice="alloy", language="en")
            req.tts_audio_base64 = synth.audio_base64
        except Exception as exc:
            log.warning("[voice_confirm] retry TTS synthesis failed: %s", exc)
        req.response_text = response_text  # keep for audit
        return req

    # Second unclear response → fall back to manual approval
    log.info(
        "[voice_confirm] unclear response (attempt 2) for %s – falling back to manual",
        confirmation_id,
    )
    _unclear_count.pop(confirmation_id, None)
    return await _expire_to_manual(req, db)


async def _expire_to_manual(req: ConfirmationRequest, db: Any = None) -> ConfirmationRequest:
    """
    Mark the confirmation as expired and ensure the linked ApprovalRequest
    is kept in ``pending`` status so the user can approve it via the UI.

    Voice confirmation gives up; the action will not run until the user
    manually approves through the Approvals page.
    """
    req.status = "expired"
    _pending.pop(req.confirmation_id, None)
    _unclear_count.pop(req.confirmation_id, None)

    # Log to audit (best-effort)
    if db is not None and req.approval_id is not None:
        try:
            from app.services.audit_service import record_action
            await record_action(
                db,
                req.action,
                req.action,
                "voice_timeout",
                (
                    f"Voice confirmation {req.confirmation_id} expired/unresolved "
                    f"for approval #{req.approval_id}. Approval remains pending "
                    f"– manual action required."
                ),
            )
        except Exception as exc:
            log.warning("[voice_confirm] audit log failed on expire: %s", exc)

    log.info(
        "[voice_confirm] confirmation %s expired → approval_id=%s left as 'pending' for manual review",
        req.confirmation_id,
        req.approval_id,
    )
    return req


# ─── Background TTL sweeper ───────────────────────────────────────────────────

async def sweep_expired_confirmations(db: Any = None) -> int:
    """
    Expire all TTL-overdue confirmations and fall back to manual approval.

    Should be called periodically (e.g. every 30 s) by a background task.
    Returns the number of confirmations expired.
    """
    now = datetime.datetime.utcnow()
    to_expire = [
        req for req in list(_pending.values())
        if now > req.expires_at
    ]
    for req in to_expire:
        await _expire_to_manual(req, db)
    if to_expire:
        log.info("[voice_confirm] swept %d expired confirmation(s)", len(to_expire))
    return len(to_expire)
