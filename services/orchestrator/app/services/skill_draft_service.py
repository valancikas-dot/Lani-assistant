"""
Skill Draft Service – Phase 7: Proposal → Skill Scaffold Generator.

Orchestrates the full draft lifecycle:

  generate_draft  → load approved SkillProposal → SkillSpec → scaffold → persist
  get_draft       → fetch by id
  list_drafts     → paginated list, optionally filtered by proposal_id
  test_draft      → run sandbox validation, update test_report
  approve_draft   → mark as approved (pre-install review step)
  request_install → create ApprovalRequest, set status=install_requested
  discard_draft   → soft-delete (status=discarded)
  draft_to_dict   → serialise SkillDraft → plain dict for API responses

Design constraints
──────────────────
• NO execution – no subprocess, no eval, no importlib.import_module.
• Install is a two-phase operation: approve first, then approve_service
  creates the real ApprovalRequest.
• The function request_install only creates an approval record and updates
  status; it does NOT trigger any execution.
"""

from __future__ import annotations

import datetime
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.skill_draft import SkillDraft
from app.models.skill_proposal import SkillProposal
from app.services.skill_spec_generator import generate_spec
from app.services.scaffold_generator import generate_scaffold
from app.services.scaffold_sandbox import run_sandbox_test

log = logging.getLogger(__name__)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def draft_to_dict(draft: SkillDraft) -> Dict[str, Any]:
    """Serialise a SkillDraft ORM row into a plain dict for API responses."""
    return {
        "id": draft.id,
        "proposal_id": draft.proposal_id,
        "name": draft.name,
        "description": draft.description,
        "spec_json": draft.spec_json,
        "scaffold_json": draft.scaffold_json,
        "scaffold_type": draft.scaffold_type,
        "risk_level": draft.risk_level,
        "status": draft.status,
        "test_report": draft.test_report,
        "tested_at": draft.tested_at.isoformat() if draft.tested_at else None,
        "approval_request_id": draft.approval_request_id,
        "installed_at": draft.installed_at.isoformat() if draft.installed_at else None,
        "reviewed": draft.reviewed,
        "created_at": draft.created_at.isoformat() if draft.created_at else None,
    }


async def _load_draft(db: AsyncSession, draft_id: int) -> Optional[SkillDraft]:
    result = await db.execute(
        select(SkillDraft).where(SkillDraft.id == draft_id)
    )
    return result.scalar_one_or_none()


async def _load_proposal(db: AsyncSession, proposal_id: int) -> Optional[SkillProposal]:
    result = await db.execute(
        select(SkillProposal).where(SkillProposal.id == proposal_id)
    )
    return result.scalar_one_or_none()


# ─── Public CRUD ─────────────────────────────────────────────────────────────

async def generate_draft(
    db: AsyncSession,
    proposal_id: int,
) -> Optional[SkillDraft]:
    """
    Convert an *approved* SkillProposal into a SkillDraft.

    Steps
    ─────
    1. Load the SkillProposal; verify status == "approved".
    2. Call ``generate_spec(proposal)`` → SkillSpec (pure function).
    3. Call ``generate_scaffold(spec)`` → scaffold dict (pure function).
    4. Persist a new SkillDraft row with status="draft".
    5. Return the persisted draft.

    Returns ``None`` if the proposal does not exist or is not approved.
    """
    proposal = await _load_proposal(db, proposal_id)
    if proposal is None:
        log.warning("[skill_draft] proposal %d not found", proposal_id)
        return None

    if proposal.status != "approved":
        log.warning(
            "[skill_draft] proposal %d has status=%r; must be 'approved'",
            proposal_id,
            proposal.status,
        )
        return None

    # Pure spec generation (no I/O)
    spec = generate_spec(proposal)

    # Pure scaffold generation (no I/O)
    scaffold = generate_scaffold(spec)

    draft = SkillDraft(
        proposal_id=proposal_id,
        name=spec.name,
        description=spec.description,
        spec_json=spec.to_dict(),
        scaffold_json=scaffold,
        scaffold_type=scaffold.get("scaffold_type", "json_workflow"),
        risk_level=spec.risk_level,
        status="draft",
        reviewed=False,
    )
    db.add(draft)
    await db.commit()
    await db.refresh(draft)

    log.info(
        "[skill_draft] generated draft id=%d for proposal %d (risk=%s)",
        draft.id,
        proposal_id,
        draft.risk_level,
    )
    return draft


async def get_draft(
    db: AsyncSession,
    draft_id: int,
) -> Optional[SkillDraft]:
    """Return a single SkillDraft by *draft_id*, or ``None`` if not found."""
    return await _load_draft(db, draft_id)


async def list_drafts(
    db: AsyncSession,
    proposal_id: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
    profile_id: Optional[int] = None,
) -> List[SkillDraft]:
    """
    List SkillDraft rows, optionally filtered by *proposal_id* and/or *profile_id*.
    Returns most-recent-first.
    """
    query = select(SkillDraft).order_by(SkillDraft.created_at.desc())
    if proposal_id is not None:
        query = query.where(SkillDraft.proposal_id == proposal_id)
    if profile_id is not None:
        query = query.where(SkillDraft.profile_id == profile_id)
    query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    return list(result.scalars().all())


async def test_draft(
    db: AsyncSession,
    draft_id: int,
) -> Optional[SkillDraft]:
    """
    Run the sandbox validation checks against the draft's scaffold.

    Steps
    ─────
    1. Load draft; must be in status "draft" or "tested" (re-test allowed).
    2. Call ``run_sandbox_test(scaffold)`` → SandboxTestReport (pure function).
    3. Persist test_report + tested_at + status="tested".
    4. Return the updated draft.

    Returns ``None`` if the draft is not found.
    """
    draft = await _load_draft(db, draft_id)
    if draft is None:
        log.warning("[skill_draft] test_draft: draft %d not found", draft_id)
        return None

    if draft.status in ("installed", "discarded"):
        log.warning(
            "[skill_draft] test_draft: draft %d has status=%r; cannot test",
            draft_id,
            draft.status,
        )
        return draft  # return unchanged so the caller can surface the state

    scaffold = draft.scaffold_json or {}
    report = run_sandbox_test(scaffold)

    draft.test_report = report.to_dict()
    draft.tested_at = datetime.datetime.utcnow()
    draft.status = "tested"

    await db.commit()
    await db.refresh(draft)

    log.info(
        "[skill_draft] tested draft id=%d: passed=%s errors=%d warnings=%d",
        draft_id,
        report.passed,
        report.error_count,
        report.warning_count,
    )
    return draft


async def approve_draft(
    db: AsyncSession,
    draft_id: int,
) -> Optional[SkillDraft]:
    """
    Mark the draft as reviewed/approved by the user.

    Requirements
    ────────────
    • Draft must have been tested (status == "tested").
    • The sandbox test must have passed (no errors).

    Sets ``reviewed=True`` and ``status="approved"``.
    Does NOT execute or install anything.
    """
    draft = await _load_draft(db, draft_id)
    if draft is None:
        return None

    if draft.status != "tested":
        log.warning(
            "[skill_draft] approve_draft: draft %d has status=%r; must be 'tested'",
            draft_id,
            draft.status,
        )
        return draft

    report = draft.test_report or {}
    if not report.get("passed", False):
        log.warning(
            "[skill_draft] approve_draft: draft %d sandbox test did not pass; "
            "cannot approve",
            draft_id,
        )
        return draft

    draft.reviewed = True
    draft.status = "approved"
    await db.commit()
    await db.refresh(draft)

    log.info("[skill_draft] draft %d approved by user", draft_id)
    return draft


async def request_install(
    db: AsyncSession,
    draft_id: int,
) -> Optional[SkillDraft]:
    """
    Create an install request for the draft.

    Requirements
    ────────────
    • Draft must be in status "approved".

    What this function does
    ───────────────────────
    • Sets ``status="install_requested"``.
    • Creates an ApprovalRequest record via the approval service.
    • Returns the updated draft.

    What this function does NOT do
    ───────────────────────────────
    • Does NOT execute, install, or run anything.
    • Does NOT modify any system file or config.
    • execution_guard is NOT touched.
    """
    draft = await _load_draft(db, draft_id)
    if draft is None:
        return None

    if draft.status != "approved":
        log.warning(
            "[skill_draft] request_install: draft %d has status=%r; must be 'approved'",
            draft_id,
            draft.status,
        )
        return draft

    # Create an ApprovalRequest so the user can grant final install permission
    from app.services.approval_service import create_approval_request

    approval_id = await create_approval_request(
        db=db,
        tool_name="skill_installer",
        command=f"Install skill draft: {draft.name}",
        params={
            "draft_id": draft.id,
            "proposal_id": draft.proposal_id,
            "skill_name": draft.name,
            "risk_level": draft.risk_level,
        },
        execution_context={
            "action": "skill_draft_install",
            "draft_id": draft.id,
        },
    )

    draft.status = "install_requested"
    draft.approval_request_id = approval_id
    await db.commit()
    await db.refresh(draft)

    log.info(
        "[skill_draft] install requested for draft %d "
        "(approval_request_id=%d)",
        draft_id,
        draft.approval_request_id or 0,
    )
    return draft


async def discard_draft(
    db: AsyncSession,
    draft_id: int,
) -> Optional[SkillDraft]:
    """
    Discard a draft.  Sets ``status="discarded"``.
    The row is kept for audit purposes – not deleted from the DB.

    Can be called on any draft that has not yet been installed.
    """
    draft = await _load_draft(db, draft_id)
    if draft is None:
        return None

    if draft.status == "installed":
        log.warning(
            "[skill_draft] discard_draft: draft %d is already installed; "
            "cannot discard",
            draft_id,
        )
        return draft

    draft.status = "discarded"
    await db.commit()
    await db.refresh(draft)

    log.info("[skill_draft] draft %d discarded", draft_id)
    return draft


# ─── Phase 9: Finalize Install ───────────────────────────────────────────────

async def finalize_install(
    db: AsyncSession,
    draft_id: int,
) -> Optional[dict]:
    """
    Finalize the installation of a SkillDraft that has an approved
    ApprovalRequest.

    Delegates to ``installed_skill_service.finalize_install()`` which:
      • validates the approval
      • creates (or upgrades) the InstalledSkill registry entry
      • appends an InstalledSkillVersion audit row
      • sets draft.status = "installed"

    Returns a dict with ``{"draft": ..., "skill": ...}`` on success,
    or ``None`` on any precondition failure.
    """
    # Late import to avoid circular dependency at module load time
    from app.services import installed_skill_service as iss
    from app.services.skill_draft_service import draft_to_dict

    skill = await iss.finalize_install(db, draft_id)
    if skill is None:
        return None

    # Reload draft (finalize_install committed changes to it)
    draft = await _load_draft(db, draft_id)
    await db.commit()
    if draft:
        await db.refresh(draft)

    return {
        "draft": draft_to_dict(draft) if draft else None,
        "skill": iss.skill_to_dict(skill),
    }
