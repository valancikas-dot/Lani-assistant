"""
API routes for Voice Confirmation Loop.

GET  /api/v1/voice/confirmations              – list pending confirmations
GET  /api/v1/voice/confirmation/{cid}         – get one confirmation
POST /api/v1/voice/confirmation/{cid}/respond – respond (text or transcript)
POST /api/v1/voice/confirmation/create        – create a confirmation (for testing)
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.services import voice_confirmation

router = APIRouter()


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


@router.get("/voice/confirmations", tags=["voice"])
async def list_pending_confirmations() -> Dict[str, Any]:
    """Return all pending voice confirmation requests."""
    pending = voice_confirmation.list_pending_confirmations()
    return {"confirmations": pending, "total": len(pending)}


@router.get("/voice/confirmation/{cid}", tags=["voice"])
async def get_confirmation(cid: str) -> Dict[str, Any]:
    """Get the status of a single confirmation request."""
    req = voice_confirmation.get_confirmation(cid)
    if req is None:
        return {"ok": False, "message": "Confirmation not found or expired."}
    return {"ok": True, "confirmation": req.to_dict()}


@router.post("/voice/confirmation/{cid}/respond", tags=["voice"])
async def respond_to_confirmation(
    cid: str,
    body: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Submit a response (spoken text / typed text) to a pending confirmation.

    Body: { "response_text": "yes" }
    """
    text = body.get("response_text", "").strip()
    if not text:
        return {"ok": False, "message": "response_text is required."}

    req = await voice_confirmation.respond(cid, text, db)
    if req is None:
        return {"ok": False, "message": "Confirmation not found."}

    return {"ok": True, "status": req.status, "verdict": req.status}


@router.post("/voice/confirmation/create", tags=["voice"])
async def create_confirmation(body: Dict[str, Any]) -> Dict[str, Any]:
    """
    Manually create a voice confirmation (useful for testing / manual trigger).

    Body: { "prompt": "...", "action": "tool_name", "risk_level": "high" }
    """
    prompt = body.get("prompt", "")
    action = body.get("action", "unknown")
    risk_level = body.get("risk_level", "high")
    approval_id = body.get("approval_id")

    req = await voice_confirmation.request_voice_confirmation(
        prompt=prompt,
        action=action,
        approval_id=approval_id,
        risk_level=risk_level,
        synthesise_tts=body.get("synthesise_tts", True),
    )
    return {"ok": True, "confirmation": req.to_dict()}
