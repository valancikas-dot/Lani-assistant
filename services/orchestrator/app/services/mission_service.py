"""
Mission Service (Phase 8 – Autonomous Missions with Checkpoints).

Provides the full mission lifecycle:
  create_mission        – instantiate a new planned mission
  start_mission         – transition planned → running
  pause_mission         – transition running → paused
  resume_mission        – transition paused → running
  cancel_mission        – transition any active status → cancelled
  advance_step          – record a completed step, update progress + budgets
  create_checkpoint     – create a human-gate (status → waiting_approval)
  resolve_checkpoint    – approve or deny a pending checkpoint
  get_mission           – fetch single mission by id
  list_missions         – list missions with optional status filter
  get_checkpoints       – list all checkpoints for a mission
  mission_to_dict       – serialise Mission ORM row → dict
  checkpoint_to_dict    – serialise MissionCheckpoint ORM row → dict

Safety invariants (enforced here, NOT in routes)
─────────────────────────────────────────────────
• Budget overruns set status → failed immediately.
• A denied checkpoint always sets Mission.status → failed.
• No automatic resume after denial.
• Advancing past total_steps marks the mission completed.
• Every status transition updates updated_at.

NOTE: This service does NOT call execution_guard directly.
      The caller (plan executor / route handler) is responsible for calling
      guarded_execute() BEFORE calling advance_step() or create_checkpoint().
      This preserves a clean separation of concerns.
"""

from __future__ import annotations

import datetime
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mission import (
    Mission,
    MISSION_STATUS_PLANNED,
    MISSION_STATUS_RUNNING,
    MISSION_STATUS_WAITING_APPROVAL,
    MISSION_STATUS_PAUSED,
    MISSION_STATUS_COMPLETED,
    MISSION_STATUS_FAILED,
    MISSION_STATUS_CANCELLED,
    CHECKPOINT_POLICY_RISKY,
)
from app.models.mission_checkpoint import (
    MissionCheckpoint,
    CHECKPOINT_STATUS_PENDING,
    CHECKPOINT_STATUS_APPROVED,
    CHECKPOINT_STATUS_DENIED,
)

log = logging.getLogger(__name__)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _now() -> datetime.datetime:
    return datetime.datetime.utcnow()


def _recalc_progress(mission: Mission) -> None:
    """Recompute progress_percent from current_step / total_steps."""
    if mission.total_steps > 0:
        mission.progress_percent = round(
            min(mission.current_step / mission.total_steps, 1.0) * 100.0, 1
        )
    else:
        mission.progress_percent = 0.0


def _touch(mission: Mission) -> None:
    """Stamp updated_at on every mutation."""
    mission.updated_at = _now()


# ─── CRUD ─────────────────────────────────────────────────────────────────────

async def create_mission(
    db: AsyncSession,
    title: str,
    goal: str,
    total_steps: int = 0,
    *,
    budget_tokens: Optional[int] = None,
    budget_time_ms: Optional[int] = None,
    checkpoint_policy: str = CHECKPOINT_POLICY_RISKY,
    session_id: Optional[str] = None,
) -> Mission:
    """Create a new mission in *planned* status."""
    mission = Mission(
        title=title,
        goal=goal,
        total_steps=max(0, total_steps),
        status=MISSION_STATUS_PLANNED,
        current_step=0,
        progress_percent=0.0,
        budget_tokens=budget_tokens,
        budget_time_ms=budget_time_ms,
        tokens_used=0,
        elapsed_time_ms=0,
        checkpoint_policy=checkpoint_policy,
        chain_ids=[],
        session_id=session_id,
    )
    _touch(mission)
    db.add(mission)
    await db.flush()
    log.info("[mission] created id=%s title=%r total_steps=%d", mission.id, title, total_steps)
    return mission


async def get_mission(db: AsyncSession, mission_id: int) -> Optional[Mission]:
    """Fetch a single mission by primary key."""
    result = await db.execute(select(Mission).where(Mission.id == mission_id))
    return result.scalar_one_or_none()


async def list_missions(
    db: AsyncSession,
    status: Optional[str] = None,
    limit: int = 50,
    profile_id: Optional[int] = None,
) -> List[Mission]:
    """Return missions optionally filtered by status and/or profile, newest first."""
    q = select(Mission)
    if status:
        q = q.where(Mission.status == status)
    if profile_id is not None:
        q = q.where(Mission.profile_id == profile_id)
    q = q.order_by(Mission.created_at.desc()).limit(limit)
    result = await db.execute(q)
    return list(result.scalars().all())


# ─── Lifecycle transitions ────────────────────────────────────────────────────

async def start_mission(db: AsyncSession, mission_id: int) -> Optional[Mission]:
    """Transition *planned* → *running*."""
    mission = await get_mission(db, mission_id)
    if mission is None:
        return None
    if mission.status != MISSION_STATUS_PLANNED:
        log.warning(
            "[mission] start_mission id=%s: status is %r, expected 'planned'",
            mission_id, mission.status,
        )
        return mission
    mission.status = MISSION_STATUS_RUNNING
    mission.started_at = _now()
    _touch(mission)
    await db.flush()
    log.info("[mission] started id=%s", mission_id)
    return mission


async def pause_mission(
    db: AsyncSession,
    mission_id: int,
    reason: str = "",
) -> Optional[Mission]:
    """Transition *running* → *paused*."""
    mission = await get_mission(db, mission_id)
    if mission is None:
        return None
    if mission.status != MISSION_STATUS_RUNNING:
        log.warning(
            "[mission] pause_mission id=%s: status is %r, expected 'running'",
            mission_id, mission.status,
        )
        return mission
    mission.status = MISSION_STATUS_PAUSED
    if reason:
        mission.last_error = reason
    _touch(mission)
    await db.flush()
    log.info("[mission] paused id=%s reason=%r", mission_id, reason)
    return mission


async def resume_mission(db: AsyncSession, mission_id: int) -> Optional[Mission]:
    """Transition *paused* → *running*. Does NOT resume from waiting_approval."""
    mission = await get_mission(db, mission_id)
    if mission is None:
        return None
    if mission.status != MISSION_STATUS_PAUSED:
        log.warning(
            "[mission] resume_mission id=%s: status is %r, expected 'paused'",
            mission_id, mission.status,
        )
        return mission
    mission.status = MISSION_STATUS_RUNNING
    mission.last_error = ""  # type: ignore[assignment]
    _touch(mission)
    await db.flush()
    log.info("[mission] resumed id=%s", mission_id)
    return mission


async def cancel_mission(db: AsyncSession, mission_id: int) -> Optional[Mission]:
    """Transition any active status → *cancelled*."""
    mission = await get_mission(db, mission_id)
    if mission is None:
        return None
    terminal = {MISSION_STATUS_COMPLETED, MISSION_STATUS_FAILED, MISSION_STATUS_CANCELLED}
    if mission.status in terminal:
        log.warning(
            "[mission] cancel_mission id=%s: already terminal (%r)", mission_id, mission.status
        )
        return mission
    mission.status = MISSION_STATUS_CANCELLED
    mission.completed_at = _now()
    _touch(mission)
    await db.flush()
    log.info("[mission] cancelled id=%s", mission_id)
    return mission


# ─── Step advancement & budget enforcement ────────────────────────────────────

async def advance_step(
    db: AsyncSession,
    mission_id: int,
    chain_id: Optional[str] = None,
    *,
    tokens_used: int = 0,
    elapsed_ms: int = 0,
) -> Optional[Mission]:
    """
    Record the completion of one mission step.

    Updates progress counters, appends chain_id, and enforces budget limits.
    If a budget is exceeded the mission is immediately set to *failed*.
    If current_step reaches total_steps the mission is set to *completed*.

    Returns the updated Mission (or None if not found).
    """
    mission = await get_mission(db, mission_id)
    if mission is None:
        return None

    if mission.status != MISSION_STATUS_RUNNING:
        log.warning(
            "[mission] advance_step id=%s: status is %r, must be 'running'",
            mission_id, mission.status,
        )
        return mission

    # Append chain reference
    if chain_id:
        existing = list(mission.chain_ids or [])
        existing.append(chain_id)
        mission.chain_ids = existing

    # Accumulate resource usage
    mission.tokens_used = (mission.tokens_used or 0) + tokens_used
    mission.elapsed_time_ms = (mission.elapsed_time_ms or 0) + elapsed_ms

    # Budget enforcement – token budget
    if mission.budget_tokens is not None and mission.tokens_used > mission.budget_tokens:
        mission.status = MISSION_STATUS_FAILED
        mission.last_error = (
            f"Token budget exhausted: used {mission.tokens_used} / {mission.budget_tokens}"
        )
        mission.completed_at = _now()
        _touch(mission)
        await db.flush()
        log.warning(
            "[mission] BUDGET EXCEEDED (tokens) id=%s used=%d budget=%d",
            mission_id, mission.tokens_used, mission.budget_tokens,
        )
        return mission

    # Budget enforcement – time budget
    if mission.budget_time_ms is not None and mission.elapsed_time_ms > mission.budget_time_ms:
        mission.status = MISSION_STATUS_FAILED
        mission.last_error = (
            f"Time budget exhausted: used {mission.elapsed_time_ms}ms / {mission.budget_time_ms}ms"
        )
        mission.completed_at = _now()
        _touch(mission)
        await db.flush()
        log.warning(
            "[mission] BUDGET EXCEEDED (time) id=%s used_ms=%d budget_ms=%d",
            mission_id, mission.elapsed_time_ms, mission.budget_time_ms,
        )
        return mission

    # Advance step counter
    mission.current_step = (mission.current_step or 0) + 1
    _recalc_progress(mission)

    # Check completion
    if mission.total_steps > 0 and mission.current_step >= mission.total_steps:
        mission.status = MISSION_STATUS_COMPLETED
        mission.progress_percent = 100.0
        mission.completed_at = _now()
        log.info("[mission] completed id=%s steps=%d", mission_id, mission.current_step)

    _touch(mission)
    await db.flush()
    return mission


# ─── Checkpoints ─────────────────────────────────────────────────────────────

async def create_checkpoint(
    db: AsyncSession,
    mission_id: int,
    step_index: int,
    reason: str,
    *,
    chain_id: Optional[str] = None,
    summary: Optional[str] = None,
    approval_request_id: Optional[int] = None,
) -> Optional[MissionCheckpoint]:
    """
    Create a checkpoint and pause the parent mission (status → waiting_approval).

    Returns None if the mission is not found or is not in a state that allows
    checkpoints (must be running or planned).
    """
    mission = await get_mission(db, mission_id)
    if mission is None:
        return None

    # Only running/planned missions can receive checkpoints
    allowed = {MISSION_STATUS_RUNNING, MISSION_STATUS_PLANNED}
    if mission.status not in allowed:
        log.warning(
            "[mission] create_checkpoint id=%s: status %r cannot receive checkpoints",
            mission_id, mission.status,
        )
        return None

    # Create the checkpoint record
    cp = MissionCheckpoint(
        mission_id=mission_id,
        step_index=step_index,
        reason=reason,
        approval_required=True,
        status=CHECKPOINT_STATUS_PENDING,
        chain_id=chain_id,
        summary=summary,
        approval_request_id=approval_request_id,
    )
    db.add(cp)

    # Halt the mission until resolved
    mission.status = MISSION_STATUS_WAITING_APPROVAL
    _touch(mission)
    await db.flush()

    log.info(
        "[mission] checkpoint created id=%s mission_id=%s step=%d reason=%r",
        cp.id, mission_id, step_index, reason,
    )
    return cp


async def resolve_checkpoint(
    db: AsyncSession,
    checkpoint_id: int,
    approved: bool,
) -> Optional[MissionCheckpoint]:
    """
    Approve or deny a pending checkpoint.

    • approved=True  → checkpoint status = approved, mission status = running
    • approved=False → checkpoint status = denied,   mission status = failed

    Returns None if the checkpoint is not found or is not pending.
    """
    result = await db.execute(
        select(MissionCheckpoint).where(MissionCheckpoint.id == checkpoint_id)
    )
    cp: Optional[MissionCheckpoint] = result.scalar_one_or_none()
    if cp is None:
        return None

    if cp.status != CHECKPOINT_STATUS_PENDING:
        log.warning(
            "[mission] resolve_checkpoint id=%s: status is %r, expected 'pending'",
            checkpoint_id, cp.status,
        )
        return cp

    cp.status = CHECKPOINT_STATUS_APPROVED if approved else CHECKPOINT_STATUS_DENIED
    cp.resolved_at = _now()

    # Update parent mission
    mission = await get_mission(db, cp.mission_id)
    if mission is not None:
        if approved:
            # Resume only if the mission was waiting (not manually cancelled etc.)
            if mission.status == MISSION_STATUS_WAITING_APPROVAL:
                mission.status = MISSION_STATUS_RUNNING
                log.info("[mission] checkpoint approved → resumed id=%s", cp.mission_id)
        else:
            # Safety: denial ALWAYS halts the mission
            mission.status = MISSION_STATUS_FAILED
            mission.last_error = f"Checkpoint {checkpoint_id} denied: {cp.reason}"
            mission.completed_at = _now()
            log.warning(
                "[mission] checkpoint DENIED → failed id=%s", cp.mission_id
            )
        _touch(mission)

    await db.flush()
    return cp


async def get_checkpoints(
    db: AsyncSession,
    mission_id: int,
) -> List[MissionCheckpoint]:
    """Return all checkpoints for a mission ordered by step_index."""
    result = await db.execute(
        select(MissionCheckpoint)
        .where(MissionCheckpoint.mission_id == mission_id)
        .order_by(MissionCheckpoint.step_index.asc(), MissionCheckpoint.created_at.asc())
    )
    return list(result.scalars().all())


# ─── Serialisation ────────────────────────────────────────────────────────────

def mission_to_dict(mission: Mission) -> Dict[str, Any]:
    """Serialise a Mission ORM row to a JSON-safe dict."""
    return {
        "id": mission.id,
        "title": mission.title,
        "goal": mission.goal,
        "status": mission.status,
        "current_step": mission.current_step,
        "total_steps": mission.total_steps,
        "progress_percent": mission.progress_percent,
        "budget_tokens": mission.budget_tokens,
        "budget_time_ms": mission.budget_time_ms,
        "tokens_used": mission.tokens_used,
        "elapsed_time_ms": mission.elapsed_time_ms,
        "checkpoint_policy": mission.checkpoint_policy,
        "chain_ids": mission.chain_ids or [],
        "session_id": mission.session_id,
        "last_error": mission.last_error,
        "created_at": mission.created_at.isoformat() if mission.created_at else None,
        "updated_at": mission.updated_at.isoformat() if mission.updated_at else None,
        "started_at": mission.started_at.isoformat() if mission.started_at else None,
        "completed_at": mission.completed_at.isoformat() if mission.completed_at else None,
    }


def checkpoint_to_dict(cp: MissionCheckpoint) -> Dict[str, Any]:
    """Serialise a MissionCheckpoint ORM row to a JSON-safe dict."""
    return {
        "id": cp.id,
        "mission_id": cp.mission_id,
        "step_index": cp.step_index,
        "reason": cp.reason,
        "approval_required": cp.approval_required,
        "status": cp.status,
        "chain_id": cp.chain_id,
        "summary": cp.summary,
        "approval_request_id": cp.approval_request_id,
        "created_at": cp.created_at.isoformat() if cp.created_at else None,
        "resolved_at": cp.resolved_at.isoformat() if cp.resolved_at else None,
    }
