"""
ORM model for Autonomous Missions (Phase 8).

A Mission is a named, multi-step goal that the assistant pursues autonomously
while maintaining full human-control checkpoints and budget guardrails.

Lifecycle
─────────
  planned           – created, not yet started
  running           – actively processing steps
  waiting_approval  – paused at a checkpoint pending human approval
  paused            – manually paused by the user
  completed         – all steps finished successfully
  failed            – halted due to error, budget overrun, or denied approval
  cancelled         – explicitly cancelled by the user

Safety guarantees
─────────────────
• Every actionable step MUST go through execution_guard.guarded_execute().
• Budget overruns stop the mission immediately (status → failed).
• A denied approval checkpoint stops the mission (no auto-resume).
• All state transitions are recorded via the audit chain.
"""

import datetime
from sqlalchemy import Integer, String, Text, DateTime, JSON, Float
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# Valid status values
MISSION_STATUS_PLANNED          = "planned"
MISSION_STATUS_RUNNING          = "running"
MISSION_STATUS_WAITING_APPROVAL = "waiting_approval"
MISSION_STATUS_PAUSED           = "paused"
MISSION_STATUS_COMPLETED        = "completed"
MISSION_STATUS_FAILED           = "failed"
MISSION_STATUS_CANCELLED        = "cancelled"

MISSION_STATUSES = [
    MISSION_STATUS_PLANNED,
    MISSION_STATUS_RUNNING,
    MISSION_STATUS_WAITING_APPROVAL,
    MISSION_STATUS_PAUSED,
    MISSION_STATUS_COMPLETED,
    MISSION_STATUS_FAILED,
    MISSION_STATUS_CANCELLED,
]

# Checkpoint policies
CHECKPOINT_POLICY_RISKY  = "risky"   # create checkpoint only for high/critical risk steps
CHECKPOINT_POLICY_ALWAYS = "always"  # checkpoint before every step
CHECKPOINT_POLICY_NEVER  = "never"   # no checkpoints (use with caution)

CHECKPOINT_POLICIES = [
    CHECKPOINT_POLICY_RISKY,
    CHECKPOINT_POLICY_ALWAYS,
    CHECKPOINT_POLICY_NEVER,
]


class Mission(Base):
    """
    An autonomous multi-step mission with checkpoints and budget enforcement.
    """

    __tablename__ = "missions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=True)

    # ── Identity ──────────────────────────────────────────────────────────────
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    goal: Mapped[str] = mapped_column(Text, nullable=False)

    # ── Lifecycle ─────────────────────────────────────────────────────────────
    # planned | running | waiting_approval | paused | completed | failed | cancelled
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=MISSION_STATUS_PLANNED
    )

    # ── Progress tracking ─────────────────────────────────────────────────────
    current_step: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_steps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress_percent: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # ── Budget enforcement ────────────────────────────────────────────────────
    # Optional hard limits – None means unlimited
    budget_tokens: Mapped[int] = mapped_column(Integer, nullable=True)
    budget_time_ms: Mapped[int] = mapped_column(Integer, nullable=True)

    # Consumed resources (updated on each step)
    tokens_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    elapsed_time_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # ── Checkpoint policy ─────────────────────────────────────────────────────
    # risky | always | never
    checkpoint_policy: Mapped[str] = mapped_column(
        String(20), nullable=False, default=CHECKPOINT_POLICY_RISKY
    )

    # ── Linked execution chains ───────────────────────────────────────────────
    # List of audit chain_ids produced by guarded_execute() for each step
    chain_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    # ── Session context ───────────────────────────────────────────────────────
    session_id: Mapped[str] = mapped_column(String(120), nullable=True)

    # ── Error tracking ────────────────────────────────────────────────────────
    last_error: Mapped[str] = mapped_column(Text, nullable=True)

    # ── Started / completed timestamps ───────────────────────────────────────
    started_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=True)

    # ── Phase 10: Profile scoping ─────────────────────────────────────────────
    # NULL = legacy / global (pre-Phase-10 rows); set to profile.id on create.
    profile_id: Mapped[int] = mapped_column(Integer, nullable=True, index=True)
