"""Security-related endpoints.

  POST /security/unlock        – PIN / passphrase fallback unlock
  POST /security/set_pin       – set or update the fallback PIN
  GET  /security/status        – environment, encryption, approval policy summary

Hashing
───────
All PIN / passphrase values are hashed with **Argon2id** before storage.
If an existing stored hash uses the legacy ``sha256:`` scheme it is verified
with the old algorithm and silently upgraded to Argon2id on successful
verification (automatic migration).
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import (
    ApprovalLevel,
    APPROVAL_POLICY,
    hash_secret,
    verify_secret,
)
from app.models.audit_log import AuditLog
from app.models.settings import UserSettings
from app.services.audit_service import record_action

log = logging.getLogger(__name__)
router = APIRouter()


# ─── Helpers ──────────────────────────────────────────────────────────────────

async def _get_or_create_settings(db: AsyncSession) -> UserSettings:
    """Return the singleton UserSettings row (id=1), creating it if absent."""
    result = await db.execute(select(UserSettings).where(UserSettings.id == 1))
    row = result.scalar_one_or_none()
    if row is None:
        row = UserSettings(id=1)
        db.add(row)
        await db.flush()
    return row



class UnlockRequest(BaseModel):
    method: str   # "pin" or "passphrase"
    value: str


class SetPinRequest(BaseModel):
    pin: str
    """The plain-text PIN to set.  Min 4 characters.  Never stored raw."""


class UnlockResponse(BaseModel):
    status: str
    method: str
    upgraded: bool = False
    """True when the stored hash was silently upgraded to Argon2id."""


class PolicyEntry(BaseModel):
    tool_name: str
    level: str


class SecurityStatus(BaseModel):
    app_env: str
    connector_encryption_configured: bool
    connector_encryption_uses_dev_key: bool
    secret_key_configured: bool
    speaker_verification_enabled: bool
    fallback_pin_enabled: bool
    fallback_pin_scheme: str   # "argon2", "sha256_legacy", "none"
    fallback_passphrase_enabled: bool
    approval_policy_summary: Dict[str, int]
    """Count of tools per ApprovalLevel."""
    recent_security_events: List[Dict[str, Any]]


# ─── Unlock ───────────────────────────────────────────────────────────────────

@router.post("/security/unlock", response_model=UnlockResponse)
async def unlock(req: UnlockRequest, db: AsyncSession = Depends(get_db)):
    """Attempt a fallback unlock using PIN or passphrase."""
    user_settings = await _get_or_create_settings(db)

    if req.method == "pin":
        if not user_settings.fallback_pin_enabled or not user_settings.fallback_pin_hash:
            await record_action(db, "security.unlock.pin", "security", "error",
                                error_message="pin_not_enabled")
            raise HTTPException(status_code=403, detail="PIN unlock not configured")

        ok, needs_rehash = verify_secret(user_settings.fallback_pin_hash, req.value)
        if ok:
            user_settings.failed_voice_attempts = 0
            if needs_rehash:
                user_settings.fallback_pin_hash = hash_secret(req.value)
                log.info("Upgraded fallback PIN hash to Argon2id for settings row 1.")
            await db.flush()
            await record_action(db, "security.unlock.pin", "security", "success")
            return UnlockResponse(status="unlocked", method="pin", upgraded=needs_rehash)
        else:
            user_settings.failed_voice_attempts = (user_settings.failed_voice_attempts or 0) + 1
            await db.flush()
            await record_action(db, "security.unlock.pin", "security", "failure",
                                error_message="invalid_pin")
            raise HTTPException(status_code=403, detail="Invalid PIN")

    if req.method == "passphrase":
        if not user_settings.fallback_passphrase_enabled:
            await record_action(db, "security.unlock.passphrase", "security", "error",
                                error_message="passphrase_not_enabled")
            raise HTTPException(status_code=403, detail="Passphrase unlock not configured")

        import hmac as _hmac
        ok = _hmac.compare_digest(
            req.value.strip().lower(),
            user_settings.fallback_passphrase_hint.strip().lower()
        )
        if ok:
            user_settings.failed_voice_attempts = 0
            await db.flush()
            await record_action(db, "security.unlock.passphrase", "security", "success")
            return UnlockResponse(status="unlocked", method="passphrase")
        else:
            user_settings.failed_voice_attempts = (user_settings.failed_voice_attempts or 0) + 1
            await db.flush()
            await record_action(db, "security.unlock.passphrase", "security", "failure",
                                error_message="invalid_passphrase")
            raise HTTPException(status_code=403, detail="Invalid passphrase")

    raise HTTPException(status_code=400, detail="Unknown unlock method. Use 'pin' or 'passphrase'.")


# ─── Set PIN ──────────────────────────────────────────────────────────────────

@router.post("/security/set_pin", status_code=200)
async def set_pin(req: SetPinRequest, db: AsyncSession = Depends(get_db)):
    """Set or update the fallback PIN.  Stores an Argon2id hash only."""
    if len(req.pin) < 4:
        raise HTTPException(status_code=422, detail="PIN must be at least 4 characters.")
    user_settings = await _get_or_create_settings(db)

    user_settings.fallback_pin_hash = hash_secret(req.pin)
    user_settings.fallback_pin_enabled = True
    await db.flush()
    await record_action(db, "security.set_pin", "security", "success")
    return {"ok": True, "message": "PIN set successfully (Argon2id)."}


# ─── Security status ──────────────────────────────────────────────────────────

@router.get("/security/status", response_model=SecurityStatus)
async def security_status(db: AsyncSession = Depends(get_db)) -> SecurityStatus:
    """Return a security posture snapshot for the UI dashboard."""
    user_settings = await _get_or_create_settings(db)

    enc_key_configured = bool(
        settings.CONNECTOR_ENCRYPTION_KEY
        or os.environ.get("CONNECTOR_ENCRYPTION_KEY", "")
    )
    enc_dev_key = not enc_key_configured

    pin_scheme = "none"
    if user_settings and user_settings.fallback_pin_hash:
        h = user_settings.fallback_pin_hash
        if h.startswith("argon2:"):
            pin_scheme = "argon2"
        elif h.startswith("sha256:"):
            pin_scheme = "sha256_legacy"
        else:
            pin_scheme = "unknown"
    summary: Dict[str, int] = {lvl.value: 0 for lvl in ApprovalLevel}
    for lvl in APPROVAL_POLICY.values():
        summary[lvl.value] += 1

    result = await db.execute(
        select(AuditLog)
        .where(AuditLog.tool_name == "security")
        .order_by(AuditLog.id.desc())
        .limit(10)
    )
    raw_events = result.scalars().all()
    recent_events: List[Dict[str, Any]] = [
        {
            "id": e.id,
            "command": e.command,
            "status": e.status,
            "timestamp": e.timestamp.isoformat() if e.timestamp else None,
            "error_message": e.error_message,
        }
        for e in raw_events
    ]

    return SecurityStatus(
        app_env=settings.APP_ENV,
        connector_encryption_configured=enc_key_configured,
        connector_encryption_uses_dev_key=enc_dev_key,
        secret_key_configured=bool(settings.SECRET_KEY),
        speaker_verification_enabled=bool(
            user_settings and user_settings.speaker_verification_enabled
        ),
        fallback_pin_enabled=bool(
            user_settings and user_settings.fallback_pin_enabled
        ),
        fallback_pin_scheme=pin_scheme,
        fallback_passphrase_enabled=bool(
            user_settings and user_settings.fallback_passphrase_enabled
        ),
        approval_policy_summary=summary,
        recent_security_events=recent_events,
    )

