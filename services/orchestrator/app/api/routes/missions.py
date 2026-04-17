"""
API routes for Autonomous Missions – Phase 8.

Endpoints
─────────
POST /missions
    Create a new mission in *planned* status.

GET  /missions
    List missions (optionally filtered by status).

GET  /missions/{mission_id}
    Retrieve a single mission.

POST /missions/{mission_id}/start
    Transition planned → running.

POST /missions/{mission_id}/pause
    Transition running → paused.

POST /missions/{mission_id}/resume
    Transition paused → running.

POST /missions/{mission_id}/cancel
    Cancel an active mission.

POST /missions/{mission_id}/advance
    Record a completed step (update progress + budgets).

GET  /missions/{mission_id}/checkpoints
    List all checkpoints for a mission.

POST /missions/{mission_id}/checkpoints
    Manually create a checkpoint (halts mission).

POST /missions/{mission_id}/checkpoints/{checkpoint_id}/resolve
    Approve or deny a pending checkpoint.

Safety
──────
• All state changes are funnelled through mission_service which enforces
  budget limits and checkpoint safety invariants.
• No execution of arbitrary code happens in these routes.
• Callers that actually execute steps must call execution_guard.guarded_execute()
  BEFORE calling POST /advance.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services import mission_service as svc
from app.models.mission import CHECKPOINT_POLICIES, MISSION_STATUSES

router = APIRouter()


# ─── Request / response schemas ──────────────────────────────────────────────

class CreateMissionRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=240)
    goal: str = Field(..., min_length=1)
    total_steps: int = Field(default=0, ge=0)
    budget_tokens: Optional[int] = Field(default=None, ge=1)
    budget_time_ms: Optional[int] = Field(default=None, ge=1)
    checkpoint_policy: str = Field(default="risky")
    session_id: Optional[str] = None


class PauseMissionRequest(BaseModel):
    reason: str = Field(default="")


class AdvanceStepRequest(BaseModel):
    chain_id: Optional[str] = None
    tokens_used: int = Field(default=0, ge=0)
    elapsed_ms: int = Field(default=0, ge=0)


class CreateCheckpointRequest(BaseModel):
    step_index: int = Field(default=0, ge=0)
    reason: str = Field(..., min_length=1)
    chain_id: Optional[str] = None
    summary: Optional[str] = None
    approval_request_id: Optional[int] = None


class ResolveCheckpointRequest(BaseModel):
    approved: bool


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _not_found(mission_id: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Mission {mission_id} not found.",
    )


def _cp_not_found(checkpoint_id: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Checkpoint {checkpoint_id} not found.",
    )


def _bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


# ─── Create ──────────────────────────────────────────────────────────────────

@router.post(
    "/missions",
    summary="Create a new autonomous mission",
    status_code=status.HTTP_201_CREATED,
)
async def create_mission(
    body: CreateMissionRequest,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Create a mission in *planned* status."""
    if body.checkpoint_policy not in CHECKPOINT_POLICIES:
        raise _bad_request(
            f"Invalid checkpoint_policy '{body.checkpoint_policy}'. "
            f"Must be one of: {CHECKPOINT_POLICIES}"
        )
    mission = await svc.create_mission(
        db,
        title=body.title,
        goal=body.goal,
        total_steps=body.total_steps,
        budget_tokens=body.budget_tokens,
        budget_time_ms=body.budget_time_ms,
        checkpoint_policy=body.checkpoint_policy,
        session_id=body.session_id,
    )
    return svc.mission_to_dict(mission)


# ─── List ─────────────────────────────────────────────────────────────────────

@router.get(
    "/missions",
    summary="List missions",
)
async def list_missions(
    mission_status: Optional[str] = Query(
        default=None,
        alias="status",
        description="Filter by status (planned/running/waiting_approval/paused/completed/failed/cancelled)",
    ),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Return missions, newest first, optionally filtered by status."""
    if mission_status and mission_status not in MISSION_STATUSES:
        raise _bad_request(
            f"Invalid status '{mission_status}'. Must be one of: {MISSION_STATUSES}"
        )
    missions = await svc.list_missions(db, status=mission_status, limit=limit)
    return {
        "total": len(missions),
        "missions": [svc.mission_to_dict(m) for m in missions],
    }


# ─── Get ──────────────────────────────────────────────────────────────────────

@router.get(
    "/missions/{mission_id}",
    summary="Get a mission by ID",
)
async def get_mission(
    mission_id: int,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    mission = await svc.get_mission(db, mission_id)
    if mission is None:
        raise _not_found(mission_id)
    return svc.mission_to_dict(mission)


# ─── Start ────────────────────────────────────────────────────────────────────

@router.post(
    "/missions/{mission_id}/start",
    summary="Start a planned mission",
)
async def start_mission(
    mission_id: int,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    mission = await svc.start_mission(db, mission_id)
    if mission is None:
        raise _not_found(mission_id)
    return svc.mission_to_dict(mission)


# ─── Pause ────────────────────────────────────────────────────────────────────

@router.post(
    "/missions/{mission_id}/pause",
    summary="Pause a running mission",
)
async def pause_mission(
    mission_id: int,
    body: PauseMissionRequest = PauseMissionRequest(),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    mission = await svc.pause_mission(db, mission_id, reason=body.reason)
    if mission is None:
        raise _not_found(mission_id)
    return svc.mission_to_dict(mission)


# ─── Resume ───────────────────────────────────────────────────────────────────

@router.post(
    "/missions/{mission_id}/resume",
    summary="Resume a paused mission",
)
async def resume_mission(
    mission_id: int,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    mission = await svc.resume_mission(db, mission_id)
    if mission is None:
        raise _not_found(mission_id)
    return svc.mission_to_dict(mission)


# ─── Cancel ───────────────────────────────────────────────────────────────────

@router.post(
    "/missions/{mission_id}/cancel",
    summary="Cancel an active mission",
)
async def cancel_mission(
    mission_id: int,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    mission = await svc.cancel_mission(db, mission_id)
    if mission is None:
        raise _not_found(mission_id)
    return svc.mission_to_dict(mission)


# ─── Advance step ─────────────────────────────────────────────────────────────

@router.post(
    "/missions/{mission_id}/advance",
    summary="Record completion of one mission step",
)
async def advance_step(
    mission_id: int,
    body: AdvanceStepRequest = AdvanceStepRequest(),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Advance the mission by one step.

    The caller MUST have already called execution_guard.guarded_execute()
    for the step and passes the resulting chain_id here for audit linkage.
    """
    mission = await svc.advance_step(
        db,
        mission_id,
        chain_id=body.chain_id,
        tokens_used=body.tokens_used,
        elapsed_ms=body.elapsed_ms,
    )
    if mission is None:
        raise _not_found(mission_id)
    return svc.mission_to_dict(mission)


# ─── Checkpoints ─────────────────────────────────────────────────────────────

@router.get(
    "/missions/{mission_id}/checkpoints",
    summary="List checkpoints for a mission",
)
async def list_checkpoints(
    mission_id: int,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    mission = await svc.get_mission(db, mission_id)
    if mission is None:
        raise _not_found(mission_id)
    checkpoints = await svc.get_checkpoints(db, mission_id)
    return {
        "total": len(checkpoints),
        "checkpoints": [svc.checkpoint_to_dict(cp) for cp in checkpoints],
    }


@router.post(
    "/missions/{mission_id}/checkpoints",
    summary="Create a checkpoint (halts mission)",
    status_code=status.HTTP_201_CREATED,
)
async def create_checkpoint(
    mission_id: int,
    body: CreateCheckpointRequest,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Manually create a checkpoint for the mission.

    The mission must be *running* or *planned*.  Status is set to
    *waiting_approval* until the checkpoint is resolved.
    """
    cp = await svc.create_checkpoint(
        db,
        mission_id=mission_id,
        step_index=body.step_index,
        reason=body.reason,
        chain_id=body.chain_id,
        summary=body.summary,
        approval_request_id=body.approval_request_id,
    )
    if cp is None:
        # Could be mission not found OR wrong status
        mission = await svc.get_mission(db, mission_id)
        if mission is None:
            raise _not_found(mission_id)
        raise _bad_request(
            f"Cannot create checkpoint for mission in status '{mission.status}'."
        )
    return svc.checkpoint_to_dict(cp)


@router.post(
    "/missions/{mission_id}/checkpoints/{checkpoint_id}/resolve",
    summary="Approve or deny a pending checkpoint",
)
async def resolve_checkpoint(
    mission_id: int,
    checkpoint_id: int,
    body: ResolveCheckpointRequest,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Resolve a pending checkpoint.

    * ``approved=true``  → checkpoint approved, mission resumes running
    * ``approved=false`` → checkpoint denied,   mission is halted (failed)
    """
    # Verify the checkpoint belongs to this mission
    cp_check = await svc.get_checkpoints(db, mission_id)
    if not any(c.id == checkpoint_id for c in cp_check):
        # Check if it exists at all
        from sqlalchemy import select
        from app.models.mission_checkpoint import MissionCheckpoint
        row = await db.execute(
            select(MissionCheckpoint).where(MissionCheckpoint.id == checkpoint_id)
        )
        if row.scalar_one_or_none() is None:
            raise _cp_not_found(checkpoint_id)
        raise _bad_request(
            f"Checkpoint {checkpoint_id} does not belong to mission {mission_id}."
        )

    cp = await svc.resolve_checkpoint(db, checkpoint_id, approved=body.approved)
    if cp is None:
        raise _cp_not_found(checkpoint_id)
    return svc.checkpoint_to_dict(cp)
