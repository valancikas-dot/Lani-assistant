"""
Skill Proposals API – Phase 6 / 6.5.

Routes
──────
  GET  /api/v1/skill-proposals                      – list proposals (ranked)
  GET  /api/v1/skill-proposals/{id}                 – single proposal
  POST /api/v1/skill-proposals/scan                 – trigger a fresh pattern scan
  POST /api/v1/skill-proposals/{id}/approve         – mark as approved (read-only, safe)
  POST /api/v1/skill-proposals/{id}/reject          – mark as rejected
  POST /api/v1/skill-proposals/{id}/feedback        – record useful/not_useful/ignored
  POST /api/v1/skill-proposals/{id}/dismiss         – soft-hide a proposal

Safety: approve does NOT execute or install anything.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services import skill_proposal_service as svc

log = logging.getLogger(__name__)
router = APIRouter()


# ─── Request bodies ───────────────────────────────────────────────────────────

class FeedbackRequest(BaseModel):
    signal: str  # "useful" | "not_useful" | "ignored"

    @field_validator("signal")
    @classmethod
    def _validate_signal(cls, v: str) -> str:
        allowed = {"useful", "not_useful", "ignored"}
        if v not in allowed:
            raise ValueError(f"signal must be one of {sorted(allowed)}")
        return v


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/skill-proposals", tags=["skill-proposals"])
async def list_skill_proposals(
    status: Optional[str] = Query(
        default=None,
        description="Filter by status: proposed | approved | rejected",
    ),
    limit: int = Query(default=50, ge=1, le=200),
    include_dismissed: bool = Query(
        default=False,
        description="Include dismissed proposals in the response",
    ),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Return skill proposals sorted by relevance, optionally filtered by status."""
    proposals = await svc.list_proposals(
        db, status=status, limit=limit, include_dismissed=include_dismissed
    )
    return {
        "proposals": [svc.proposal_to_dict(p) for p in proposals],
        "total": len(proposals),
    }


@router.get("/skill-proposals/{proposal_id}", tags=["skill-proposals"])
async def get_skill_proposal(
    proposal_id: int,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Return a single skill proposal by id."""
    from sqlalchemy import select
    from app.models.skill_proposal import SkillProposal

    result = await db.execute(
        select(SkillProposal).where(SkillProposal.id == proposal_id)
    )
    proposal = result.scalar_one_or_none()
    if proposal is None:
        raise HTTPException(status_code=404, detail=f"Skill proposal #{proposal_id} not found.")
    return {"proposal": svc.proposal_to_dict(proposal)}


@router.post("/skill-proposals/scan", tags=["skill-proposals"])
async def scan_for_proposals(
    min_frequency: int = Query(
        default=3, ge=2, le=20,
        description="Minimum number of matching chains to form a pattern",
    ),
    min_confidence: float = Query(
        default=0.0, ge=0.0, le=1.0,
        description="Minimum confidence threshold (0.0 = no filter)",
    ),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Trigger a fresh pattern detection scan and persist any new proposals.

    Idempotent – existing proposals for the same pattern are not duplicated.
    """
    created = await svc.run_detection_and_propose(
        db, min_frequency=min_frequency, min_confidence=min_confidence
    )
    return {
        "ok": True,
        "proposals_created": len(created),
        "proposals": [svc.proposal_to_dict(p) for p in created],
    }


@router.post("/skill-proposals/{proposal_id}/approve", tags=["skill-proposals"])
async def approve_skill_proposal(
    proposal_id: int,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Mark a skill proposal as approved.

    **Safe mode**: this only updates the status field.
    It does NOT execute, install, or generate any code.
    """
    proposal = await svc.approve_proposal(db, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail=f"Skill proposal #{proposal_id} not found.")
    return {
        "ok": True,
        "message": f"Proposal #{proposal_id} approved (no code installed).",
        "proposal": svc.proposal_to_dict(proposal),
    }


@router.post("/skill-proposals/{proposal_id}/reject", tags=["skill-proposals"])
async def reject_skill_proposal(
    proposal_id: int,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Mark a skill proposal as rejected."""
    proposal = await svc.reject_proposal(db, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail=f"Skill proposal #{proposal_id} not found.")
    return {
        "ok": True,
        "message": f"Proposal #{proposal_id} rejected.",
        "proposal": svc.proposal_to_dict(proposal),
    }


@router.post("/skill-proposals/{proposal_id}/feedback", tags=["skill-proposals"])
async def feedback_skill_proposal(
    proposal_id: int,
    body: FeedbackRequest,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Record a user feedback signal on a proposal.

    Accepted signals: ``useful`` | ``not_useful`` | ``ignored``

    Updates ``feedback_score`` (running average in [-1, +1]),
    ``feedback_count``, ``last_feedback_at``, and refreshes ``relevance_score``.
    """
    proposal = await svc.record_feedback(db, proposal_id, body.signal)  # type: ignore[arg-type]
    if proposal is None:
        raise HTTPException(status_code=404, detail=f"Skill proposal #{proposal_id} not found.")
    return {
        "ok": True,
        "message": f"Feedback '{body.signal}' recorded for proposal #{proposal_id}.",
        "proposal": svc.proposal_to_dict(proposal),
    }


@router.post("/skill-proposals/{proposal_id}/dismiss", tags=["skill-proposals"])
async def dismiss_skill_proposal(
    proposal_id: int,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Soft-hide a proposal.

    Sets ``dismissed=true`` so it is excluded from default list views.
    Does NOT change ``status`` — the proposal can still be found via
    ``GET /skill-proposals?include_dismissed=true``.
    """
    proposal = await svc.dismiss_proposal(db, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail=f"Skill proposal #{proposal_id} not found.")
    return {
        "ok": True,
        "message": f"Proposal #{proposal_id} dismissed.",
        "proposal": svc.proposal_to_dict(proposal),
    }
