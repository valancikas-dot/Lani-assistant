"""
API routes for Modes – Phase 11: Mode System.

Route ordering note
───────────────────
Literal path segments (/active, /suggestions) are registered BEFORE the
path-parameter segment (/{mode_id}) so FastAPI does not match them as IDs.

Endpoints
─────────
GET  /modes                      – list all modes (filter: category, status)
GET  /modes/active               – active modes for the caller's profile
GET  /modes/suggestions          – suggest modes based on usage history
POST /modes/select               – bulk-replace active set (onboarding)
POST /modes                      – create a custom mode
GET  /modes/{mode_id}            – get a single mode with is_active flag
POST /modes/{mode_id}/activate   – activate a mode
POST /modes/{mode_id}/deactivate – deactivate a mode
POST /modes/{mode_id}/archive    – soft-delete a custom mode
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.mode import MODE_STATUS_ARCHIVED
from app.services import mode_service as svc
from app.services.mode_suggestion_service import suggest_modes, ModeSuggestion

log = logging.getLogger(__name__)
router = APIRouter(tags=["modes"])


# ─── Request / Response bodies ────────────────────────────────────────────────

class SelectModesRequest(BaseModel):
    mode_ids: List[int] = Field(..., description="IDs of modes to activate")
    profile_id: Optional[int] = Field(default=None)


class CreateModeRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: str = Field(default="")
    icon: str = Field(default="default", max_length=40)
    tagline: str = Field(default="", max_length=200)
    system_prompt_hint: str = Field(default="")
    preferred_tools: List[str] = Field(default_factory=list)
    capability_tags: List[str] = Field(default_factory=list)
    category: str = Field(default="custom")
    meta_json: Dict[str, Any] = Field(default_factory=dict)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _not_found(mode_id: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Mode {mode_id} not found",
    )


async def _active_set(db: AsyncSession, profile_id: Optional[int]) -> set[int]:
    active = await svc.get_active_modes(db, profile_id)
    return {m.id for m in active}


# ─── GET /modes ───────────────────────────────────────────────────────────────

@router.get("/modes")
async def list_modes(
    category: Optional[str] = Query(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    profile_id: Optional[int] = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    modes = await svc.list_modes(db, category=category, status=status_filter)
    active_ids = await _active_set(db, profile_id)
    return {
        "ok": True,
        "total": len(modes),
        "modes": [svc.mode_to_dict(m, is_active=m.id in active_ids) for m in modes],
    }


# ─── GET /modes/active  (MUST be before /{mode_id}) ───────────────────────────

@router.get("/modes/active")
async def get_active_modes(
    profile_id: Optional[int] = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    modes = await svc.get_active_modes(db, profile_id=profile_id)
    return {
        "ok": True,
        "total": len(modes),
        "modes": [svc.mode_to_dict(m, is_active=True) for m in modes],
    }


# ─── GET /modes/suggestions  (MUST be before /{mode_id}) ──────────────────────

@router.get("/modes/suggestions")
async def get_mode_suggestions(
    profile_id: Optional[int] = Query(default=None),
    top_k: int = Query(default=3, ge=1, le=10),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    suggestions: List[ModeSuggestion] = await suggest_modes(
        db, profile_id=profile_id, top_k=top_k
    )
    return {
        "ok": True,
        "suggestions": [
            {
                "mode": svc.mode_to_dict(s.mode),
                "score": round(s.score, 4),
                "reason": s.reason,
            }
            for s in suggestions
        ],
    }


# ─── POST /modes/select ───────────────────────────────────────────────────────

@router.post("/modes/select")
async def select_modes(
    body: SelectModesRequest,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Bulk-replace the active mode set for a profile.
    All previously active modes for the profile are deactivated first.
    Used by the onboarding wizard and the Settings / Modes page.
    """
    active = await svc.set_modes(db, body.mode_ids, profile_id=body.profile_id)
    await db.commit()
    return {
        "ok": True,
        "total": len(active),
        "modes": [svc.mode_to_dict(m, is_active=True) for m in active],
    }


# ─── POST /modes  (create custom) ────────────────────────────────────────────

@router.post("/modes", status_code=status.HTTP_201_CREATED)
async def create_mode(
    body: CreateModeRequest,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    mode = await svc.create_custom_mode(
        db,
        name=body.name,
        description=body.description,
        icon=body.icon,
        tagline=body.tagline,
        system_prompt_hint=body.system_prompt_hint,
        preferred_tools=body.preferred_tools,
        capability_tags=body.capability_tags,
        category=body.category,
        meta_json=body.meta_json,
    )
    await db.commit()
    return {"ok": True, "mode": svc.mode_to_dict(mode)}


# ─── GET /modes/{mode_id} ─────────────────────────────────────────────────────

@router.get("/modes/{mode_id}")
async def get_mode(
    mode_id: int,
    profile_id: Optional[int] = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    mode = await svc.get_mode(db, mode_id)
    if mode is None:
        raise _not_found(mode_id)
    active_ids = await _active_set(db, profile_id)
    return {"ok": True, "mode": svc.mode_to_dict(mode, is_active=mode_id in active_ids)}


# ─── POST /modes/{mode_id}/activate ──────────────────────────────────────────

@router.post("/modes/{mode_id}/activate")
async def activate_mode(
    mode_id: int,
    profile_id: Optional[int] = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    mode = await svc.activate_mode(db, mode_id, profile_id=profile_id)
    if mode is None:
        raise _not_found(mode_id)
    await db.commit()
    return {"ok": True, "mode": svc.mode_to_dict(mode, is_active=True)}


# ─── POST /modes/{mode_id}/deactivate ────────────────────────────────────────

@router.post("/modes/{mode_id}/deactivate")
async def deactivate_mode(
    mode_id: int,
    profile_id: Optional[int] = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    mode = await svc.deactivate_mode(db, mode_id, profile_id=profile_id)
    if mode is None:
        raise _not_found(mode_id)
    await db.commit()
    return {"ok": True, "mode": svc.mode_to_dict(mode, is_active=False)}


# ─── POST /modes/{mode_id}/archive ───────────────────────────────────────────

@router.post("/modes/{mode_id}/archive")
async def archive_mode(
    mode_id: int,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    mode = await svc.get_mode(db, mode_id)
    if mode is None:
        raise _not_found(mode_id)
    if mode.is_builtin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Built-in modes cannot be archived.",
        )
    mode.status = MODE_STATUS_ARCHIVED
    from app.services.mode_service import _now
    mode.updated_at = _now()
    await db.commit()
    return {"ok": True, "mode": svc.mode_to_dict(mode)}
