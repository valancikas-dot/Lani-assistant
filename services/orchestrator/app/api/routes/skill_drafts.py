"""
API routes for Skill Drafts – Phase 7: Proposal → Skill Scaffold Generator.

Endpoints
─────────
POST /skill-proposals/{proposal_id}/generate
    Convert an approved SkillProposal into a SkillDraft.

GET  /skill-drafts
    List drafts (optionally filtered by proposal_id).

GET  /skill-drafts/{draft_id}
    Retrieve a single draft.

POST /skill-drafts/{draft_id}/test
    Run the sandbox validation on the draft's scaffold.

POST /skill-drafts/{draft_id}/approve
    Mark the draft as reviewed/approved (after a passing sandbox test).

POST /skill-drafts/{draft_id}/install
    Request installation (creates an ApprovalRequest; does NOT execute).

POST /skill-drafts/{draft_id}/discard
    Discard the draft (soft-delete).

Safety
──────
• None of these routes execute any code from the scaffold.
• The /install endpoint only creates an approval record.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services import skill_draft_service as svc

router = APIRouter()


# ─── Helper ──────────────────────────────────────────────────────────────────

def _not_found(draft_id: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Skill draft {draft_id} not found.",
    )


def _proposal_not_found(proposal_id: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Skill proposal {proposal_id} not found.",
    )


def _bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


# ─── Generate ────────────────────────────────────────────────────────────────

@router.post(
    "/skill-proposals/{proposal_id}/generate",
    summary="Generate a skill draft from an approved proposal",
    status_code=status.HTTP_201_CREATED,
)
async def generate_draft(
    proposal_id: int,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Convert an **approved** SkillProposal into a SkillDraft.

    Returns the freshly-created draft.  The draft starts in ``status="draft"``
    and must be tested before it can be approved or installed.
    """
    draft = await svc.generate_draft(db, proposal_id)
    if draft is None:
        # Could be 404 (proposal not found) or 422 (wrong status).
        # Check which by trying a plain lookup.
        from sqlalchemy import select
        from app.models.skill_proposal import SkillProposal
        result = await db.execute(
            select(SkillProposal).where(SkillProposal.id == proposal_id)
        )
        proposal = result.scalar_one_or_none()
        if proposal is None:
            raise _proposal_not_found(proposal_id)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Proposal {proposal_id} has status='{proposal.status}'. "
                "Only approved proposals can be converted to drafts."
            ),
        )

    return {"ok": True, "draft": svc.draft_to_dict(draft)}


# ─── List ─────────────────────────────────────────────────────────────────────

@router.get(
    "/skill-drafts",
    summary="List skill drafts",
)
async def list_drafts(
    proposal_id: Optional[int] = Query(None, description="Filter by proposal"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """List all skill drafts, optionally filtered by *proposal_id*."""
    drafts = await svc.list_drafts(db, proposal_id=proposal_id, limit=limit, offset=offset)
    return {
        "drafts": [svc.draft_to_dict(d) for d in drafts],
        "total": len(drafts),
        "limit": limit,
        "offset": offset,
    }


# ─── Get one ─────────────────────────────────────────────────────────────────

@router.get(
    "/skill-drafts/{draft_id}",
    summary="Get a single skill draft",
)
async def get_draft(
    draft_id: int,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Retrieve a single skill draft by ID."""
    draft = await svc.get_draft(db, draft_id)
    if draft is None:
        raise _not_found(draft_id)
    return {"draft": svc.draft_to_dict(draft)}


# ─── Test ─────────────────────────────────────────────────────────────────────

@router.post(
    "/skill-drafts/{draft_id}/test",
    summary="Run sandbox validation on a skill draft",
)
async def test_draft(
    draft_id: int,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Run the sandbox validation checks against the draft's scaffold.

    **Safe** – no part of the scaffold is executed.  The sandbox performs
    pure structural and pattern-matching checks only.

    Sets ``status="tested"`` and populates ``test_report``.
    """
    draft = await svc.test_draft(db, draft_id)
    if draft is None:
        raise _not_found(draft_id)

    return {
        "ok": True,
        "draft": svc.draft_to_dict(draft),
        "report": draft.test_report,
    }


# ─── Approve ─────────────────────────────────────────────────────────────────

@router.post(
    "/skill-drafts/{draft_id}/approve",
    summary="Approve a tested skill draft for installation",
)
async def approve_draft(
    draft_id: int,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Mark a *tested* draft as approved.

    Requirements:
    - ``status`` must be ``"tested"``
    - The sandbox test must have ``passed=True``

    Does **not** install anything.
    """
    draft = await svc.approve_draft(db, draft_id)
    if draft is None:
        raise _not_found(draft_id)

    if draft.status not in ("approved", "install_requested", "installed"):
        # approve_draft returned without changing status → pre-condition failed
        report = draft.test_report or {}
        if draft.status != "tested":
            raise _bad_request(
                f"Draft {draft_id} has status='{draft.status}'. "
                "Draft must be tested before it can be approved."
            )
        if not report.get("passed", False):
            raise _bad_request(
                f"Draft {draft_id} sandbox test did not pass "
                f"(errors={report.get('error_count', '?')}). "
                "Fix the reported issues before approving."
            )

    return {"ok": True, "draft": svc.draft_to_dict(draft)}


# ─── Install ─────────────────────────────────────────────────────────────────

@router.post(
    "/skill-drafts/{draft_id}/install",
    summary="Request installation of an approved skill draft",
)
async def install_draft(
    draft_id: int,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Create an install request for an *approved* draft.

    This endpoint:
    - Requires ``status="approved"``
    - Creates an ``ApprovalRequest`` record
    - Sets ``status="install_requested"``
    - Returns the updated draft

    **Nothing is executed or installed automatically.**
    The user must grant the generated ApprovalRequest before any
    installation logic runs.
    """
    draft = await svc.request_install(db, draft_id)
    if draft is None:
        raise _not_found(draft_id)

    if draft.status not in ("install_requested", "installed"):
        raise _bad_request(
            f"Draft {draft_id} has status='{draft.status}'. "
            "Draft must be approved before requesting installation."
        )

    return {"ok": True, "draft": svc.draft_to_dict(draft)}


# ─── Finalize Install (Phase 9) ───────────────────────────────────────────────

@router.post(
    "/skill-drafts/{draft_id}/finalize",
    summary="Finalize the installation of an approved skill draft",
)
async def finalize_draft_install(
    draft_id: int,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Finalize the installation of a SkillDraft whose linked ApprovalRequest
    has been approved.

    On success the draft's ``status`` transitions to ``"installed"`` and an
    ``InstalledSkill`` registry entry (plus a version history row) is created.
    If the skill name already exists and is not in a terminal state, the
    existing entry is upgraded in-place.

    Pre-conditions (HTTP 422 on any failure):
    • Draft must exist.
    • Draft status must be ``"install_requested"``.
    • The linked ApprovalRequest must have ``status="approved"``.
    """
    result = await svc.finalize_install(db, draft_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Cannot finalize draft {draft_id}. "
                "Ensure the draft is in 'install_requested' status and its "
                "linked ApprovalRequest has been approved."
            ),
        )

    return {"ok": True, **result}


# ─── Discard ─────────────────────────────────────────────────────────────────

@router.post(
    "/skill-drafts/{draft_id}/discard",
    summary="Discard a skill draft",
)
async def discard_draft(
    draft_id: int,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Discard a skill draft.

    Sets ``status="discarded"``.  The record is kept for audit purposes.
    Cannot discard a draft that has already been installed.
    """
    draft = await svc.discard_draft(db, draft_id)
    if draft is None:
        raise _not_found(draft_id)

    if draft.status == "installed":
        raise _bad_request(
            f"Draft {draft_id} is already installed; it cannot be discarded."
        )

    return {"ok": True, "draft": svc.draft_to_dict(draft)}
