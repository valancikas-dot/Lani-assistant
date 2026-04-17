"""
API routes for Installed Skills – Phase 9: Installed Skills Registry + Versioning.

Endpoints
─────────
GET  /installed-skills
    List installed skills (optional status filter).

GET  /installed-skills/{skill_id}
    Retrieve a single installed skill record.

GET  /installed-skills/{skill_id}/versions
    Retrieve the full version history for a skill.

POST /installed-skills/{skill_id}/enable
    Re-activate a disabled skill.

POST /installed-skills/{skill_id}/disable
    Temporarily disable a skill (can be re-enabled later).

POST /installed-skills/{skill_id}/rollback
    Roll back to the previous version snapshot.

POST /installed-skills/{skill_id}/revoke
    Permanently revoke a skill (terminal operation).

GET  /installed-skills/capabilities
    Return installed (enabled) skills formatted as capability metadata.

Safety
──────
• Revoke is permanent; no endpoint can undo it.
• Rollback is explicit and audited.
• No code is executed by any of these routes.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services import installed_skill_service as iss

log = logging.getLogger(__name__)

router = APIRouter(tags=["installed-skills"])


# ─── Request bodies ───────────────────────────────────────────────────────────

class RevokeRequest(BaseModel):
    reason: Optional[str] = ""


# ─── Error helpers ────────────────────────────────────────────────────────────

def _not_found(skill_id: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"InstalledSkill {skill_id} not found",
    )


def _bad_request(msg: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=msg,
    )


# ─── List ─────────────────────────────────────────────────────────────────────

@router.get(
    "/installed-skills",
    summary="List installed skills",
)
async def list_installed_skills(
    status_filter: Optional[str] = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    List all installed skills, optionally filtered by status.

    Valid statuses: ``installed``, ``disabled``, ``superseded``, ``revoked``.
    """
    skills = await iss.list_skills(db, status=status_filter, limit=limit)
    return {
        "ok": True,
        "total": len(skills),
        "skills": [iss.skill_to_dict(s) for s in skills],
    }


# ─── Capabilities view ────────────────────────────────────────────────────────
# NOTE: This MUST be registered before /installed-skills/{skill_id} so that
#       FastAPI does not match the literal path segment "capabilities" as an int.

@router.get(
    "/installed-skills/capabilities",
    summary="Installed skills formatted as capability metadata",
)
async def installed_capabilities(
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Return all **enabled** installed skills formatted as capability-metadata
    dicts (same shape as ``/api/v1/capabilities``), with an extra
    ``source: "installed"`` field to distinguish them from built-in tools.
    """
    skills = await iss.list_skills(db, status="installed")
    caps = []
    for skill in skills:
        if not skill.enabled:
            continue
        spec = skill.spec_json or {}
        caps.append(
            {
                "name": skill.name,
                "description": skill.description or spec.get("description", ""),
                "parameters": spec.get("parameters", {}),
                "risk_level": skill.risk_level,
                "version": skill.current_version,
                "source": "installed",
                "enabled": True,
                "installed_at": (
                    skill.installed_at.isoformat() if skill.installed_at else None
                ),
            }
        )
    return {"ok": True, "total": len(caps), "capabilities": caps}


# ─── Get single ───────────────────────────────────────────────────────────────

@router.get(
    "/installed-skills/{skill_id}",
    summary="Get a single installed skill",
)
async def get_installed_skill(
    skill_id: int,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    skill = await iss.get_skill(db, skill_id)
    if skill is None:
        raise _not_found(skill_id)
    return {"ok": True, "skill": iss.skill_to_dict(skill)}


# ─── Version history ──────────────────────────────────────────────────────────

@router.get(
    "/installed-skills/{skill_id}/versions",
    summary="Get version history for a skill",
)
async def get_skill_versions(
    skill_id: int,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    skill = await iss.get_skill(db, skill_id)
    if skill is None:
        raise _not_found(skill_id)
    versions = await iss.get_version_history(db, skill_id)
    return {
        "ok": True,
        "skill_id": skill_id,
        "versions": [iss.version_to_dict(v) for v in versions],
    }


# ─── Enable ───────────────────────────────────────────────────────────────────

@router.post(
    "/installed-skills/{skill_id}/enable",
    summary="Enable a disabled skill",
)
async def enable_installed_skill(
    skill_id: int,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    skill = await iss.enable_skill(db, skill_id)
    if skill is None:
        raise _bad_request(
            f"Skill {skill_id} not found or is in a terminal state (revoked/superseded)."
        )
    await db.commit()
    await db.refresh(skill)
    return {"ok": True, "skill": iss.skill_to_dict(skill)}


# ─── Disable ─────────────────────────────────────────────────────────────────

@router.post(
    "/installed-skills/{skill_id}/disable",
    summary="Temporarily disable a skill",
)
async def disable_installed_skill(
    skill_id: int,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    skill = await iss.disable_skill(db, skill_id)
    if skill is None:
        raise _bad_request(
            f"Skill {skill_id} not found or is in a terminal state (revoked/superseded)."
        )
    await db.commit()
    await db.refresh(skill)
    return {"ok": True, "skill": iss.skill_to_dict(skill)}


# ─── Rollback ─────────────────────────────────────────────────────────────────

@router.post(
    "/installed-skills/{skill_id}/rollback",
    summary="Roll back a skill to its previous version",
)
async def rollback_installed_skill(
    skill_id: int,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Revert the skill to its previous version snapshot.

    Requires that the skill has a ``rollback_version`` set (i.e. at least
    one upgrade has been performed since the initial install).
    """
    skill = await iss.rollback_skill(db, skill_id)
    if skill is None:
        raise _bad_request(
            f"Skill {skill_id} cannot be rolled back. "
            "It may not exist, be in a terminal state, or have no rollback snapshot."
        )
    await db.commit()
    await db.refresh(skill)
    return {"ok": True, "skill": iss.skill_to_dict(skill)}


# ─── Revoke ───────────────────────────────────────────────────────────────────

@router.post(
    "/installed-skills/{skill_id}/revoke",
    summary="Permanently revoke a skill (cannot be undone)",
)
async def revoke_installed_skill(
    skill_id: int,
    body: RevokeRequest = RevokeRequest(),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Permanently deactivate a skill.  The skill will never pass the execution
    gate again after this operation.

    Optionally supply a ``reason`` in the request body.
    """
    skill = await iss.revoke_skill(db, skill_id, reason=body.reason or "")
    if skill is None:
        raise _not_found(skill_id)
    await db.commit()
    await db.refresh(skill)
    return {"ok": True, "skill": iss.skill_to_dict(skill)}
