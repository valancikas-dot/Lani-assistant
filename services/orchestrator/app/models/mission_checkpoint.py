"""
ORM model for Mission Checkpoints (Phase 8).

A MissionCheckpoint is a human-control gate created automatically during
mission execution whenever a step is deemed risky (or policy is 'always').

The checkpoint halts the mission (status → waiting_approval) until the user
approves or denies the pending action.

Lifecycle
─────────
  pending  – created, waiting for human decision
  approved – user approved; mission may proceed
  denied   – user denied; mission is halted (status → failed)
  skipped  – checkpoint was bypassed (only if policy allows)

Safety guarantees
─────────────────
• A denied checkpoint ALWAYS sets the parent Mission.status to 'failed'.
• There is NO automatic skipping of pending checkpoints.
• Every checkpoint resolution is auditable via created_at / resolved_at.
"""

import datetime
from sqlalchemy import Integer, String, Text, DateTime, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# Valid checkpoint status values
CHECKPOINT_STATUS_PENDING  = "pending"
CHECKPOINT_STATUS_APPROVED = "approved"
CHECKPOINT_STATUS_DENIED   = "denied"
CHECKPOINT_STATUS_SKIPPED  = "skipped"

CHECKPOINT_STATUSES = [
    CHECKPOINT_STATUS_PENDING,
    CHECKPOINT_STATUS_APPROVED,
    CHECKPOINT_STATUS_DENIED,
    CHECKPOINT_STATUS_SKIPPED,
]


class MissionCheckpoint(Base):
    """
    A human-approval gate within an autonomous mission.
    """

    __tablename__ = "mission_checkpoints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow, nullable=False
    )
    resolved_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=True)

    # ── Parent mission ────────────────────────────────────────────────────────
    mission_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    # ── Position within the mission ───────────────────────────────────────────
    step_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # ── Reason this checkpoint was created ───────────────────────────────────
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # ── Approval control ──────────────────────────────────────────────────────
    approval_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )

    # ── Lifecycle ─────────────────────────────────────────────────────────────
    # pending | approved | denied | skipped
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=CHECKPOINT_STATUS_PENDING
    )

    # ── Linked execution chain ────────────────────────────────────────────────
    # audit chain_id of the step that triggered this checkpoint
    chain_id: Mapped[str] = mapped_column(String(64), nullable=True)

    # ── Human-readable summary of what will happen ────────────────────────────
    summary: Mapped[str] = mapped_column(Text, nullable=True)

    # ── Linked approval request ───────────────────────────────────────────────
    # ID of an ApprovalRequest row if one was created for this checkpoint
    approval_request_id: Mapped[int] = mapped_column(Integer, nullable=True)
