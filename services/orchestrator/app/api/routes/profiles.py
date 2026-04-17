"""
API routes for Profiles – Phase 10: Multi-profile / Team Mode.

Endpoints
─────────
GET  /profiles
    List all profiles (optional status filter).

GET  /profiles/active
    Return the currently active profile.

POST /profiles
    Create a new profile.

GET  /profiles/{profile_id}
    Fetch a single profile with stats.

PATCH /profiles/{profile_id}
    Update name / description / security mode / meta.

POST /profiles/{profile_id}/activate
    Make this profile the active one.

POST /profiles/{profile_id}/archive
    Archive (soft-delete) a profile.

Safety
──────
• Archiving the currently-active profile leaves no profile active.
  The frontend is expected to prompt the user to choose another profile.
• Cross-profile entity access is rejected by assert_profile_scope()
  in downstream service helpers, not at the route level.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services import profile_service as svc

log = logging.getLogger(__name__)

router = APIRouter(tags=["profiles"])


# ─── Request bodies ───────────────────────────────────────────────────────────

class CreateProfileRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    profile_type: str = Field(default="personal")
    description: str = Field(default="")
    default_security_mode: str = Field(default="standard")
    meta_json: Dict[str, Any] = Field(default_factory=dict)
    activate: bool = Field(default=False)


class UpdateProfileRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    description: Optional[str] = None
    default_security_mode: Optional[str] = None
    meta_json: Optional[Dict[str, Any]] = None


# ─── Error helpers ────────────────────────────────────────────────────────────

def _not_found(profile_id: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Profile {profile_id} not found",
    )


# ─── List ─────────────────────────────────────────────────────────────────────

@router.get("/profiles", summary="List all profiles")
async def list_profiles(
    status_filter: Optional[str] = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """List profiles, optionally filtered by status (active/inactive/archived)."""
    profiles = await svc.list_profiles(db, status=status_filter, limit=limit)
    return {
        "ok": True,
        "total": len(profiles),
        "profiles": [svc.profile_to_dict(p) for p in profiles],
    }


# ─── Active profile ───────────────────────────────────────────────────────────
# NOTE: /profiles/active MUST be registered before /profiles/{profile_id}
#       so FastAPI does not match "active" as an integer profile_id.

@router.get("/profiles/active", summary="Get the currently active profile")
async def get_active_profile(
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Return the currently active profile, or null if none is active."""
    profile = await svc.get_active_profile(db)
    if profile is None:
        return {"ok": True, "profile": None}
    stats = await svc.get_profile_stats(db, profile.id)
    return {"ok": True, "profile": svc.profile_to_dict(profile, stats=stats)}


# ─── Create ───────────────────────────────────────────────────────────────────

@router.post("/profiles", summary="Create a new profile")
async def create_profile(
    body: CreateProfileRequest,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Create a new profile / workspace."""
    try:
        profile = await svc.create_profile(
            db,
            name=body.name,
            profile_type=body.profile_type,
            description=body.description,
            default_security_mode=body.default_security_mode,
            meta_json=body.meta_json,
            activate=body.activate,
        )
        await db.commit()
        await db.refresh(profile)
    except Exception as exc:
        log.warning("[profiles] create failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    return {"ok": True, "profile": svc.profile_to_dict(profile)}


# ─── Get single ───────────────────────────────────────────────────────────────

@router.get("/profiles/{profile_id}", summary="Get a single profile with stats")
async def get_profile(
    profile_id: int,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    profile = await svc.get_profile(db, profile_id)
    if profile is None:
        raise _not_found(profile_id)
    stats = await svc.get_profile_stats(db, profile_id)
    return {"ok": True, "profile": svc.profile_to_dict(profile, stats=stats)}


# ─── Update ───────────────────────────────────────────────────────────────────

@router.patch("/profiles/{profile_id}", summary="Update a profile")
async def update_profile(
    profile_id: int,
    body: UpdateProfileRequest,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    profile = await svc.update_profile(
        db,
        profile_id,
        name=body.name,
        description=body.description,
        default_security_mode=body.default_security_mode,
        meta_json=body.meta_json,
    )
    if profile is None:
        raise _not_found(profile_id)
    await db.commit()
    await db.refresh(profile)
    return {"ok": True, "profile": svc.profile_to_dict(profile)}


# ─── Activate ─────────────────────────────────────────────────────────────────

@router.post("/profiles/{profile_id}/activate", summary="Activate a profile")
async def activate_profile(
    profile_id: int,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Make the specified profile the active one; deactivate all others."""
    profile = await svc.activate_profile(db, profile_id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Profile {profile_id} not found or is archived.",
        )
    await db.commit()
    await db.refresh(profile)
    stats = await svc.get_profile_stats(db, profile_id)
    return {"ok": True, "profile": svc.profile_to_dict(profile, stats=stats)}


# ─── Archive ──────────────────────────────────────────────────────────────────

@router.post("/profiles/{profile_id}/archive", summary="Archive a profile")
async def archive_profile(
    profile_id: int,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Soft-delete a profile.  Archived profiles cannot be activated.
    Entity rows belonging to the profile are preserved.
    """
    profile = await svc.archive_profile(db, profile_id)
    if profile is None:
        raise _not_found(profile_id)
    await db.commit()
    await db.refresh(profile)
    return {"ok": True, "profile": svc.profile_to_dict(profile)}
