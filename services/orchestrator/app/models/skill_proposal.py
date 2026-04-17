"""ORM model for skill proposals (Phase 6 – Skill Proposal Engine)."""

import datetime
from sqlalchemy import Boolean, Integer, String, Text, DateTime, Float, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SkillProposal(Base):
    """
    A proposal to automate a detected recurring behaviour.

    The proposal is **read-only** until the user explicitly approves or
    rejects it.  Approval marks the status as 'approved' but does NOT
    install, execute, or generate any code automatically.

    Phase 6.5 additions
    ───────────────────
    • feedback_score   – running average of 'useful' (+1) / 'not_useful' (-1) signals
    • feedback_count   – total number of feedback events recorded
    • last_feedback_at – timestamp of most recent feedback
    • dismissed        – soft-hide flag; dismissed proposals appear under a
                         separate filter but are never hard-deleted
    • relevance_score  – pre-computed composite ranking score, refreshed on
                         every list call so the list stays sorted correctly
    • why_suggested    – short machine-generated explanation shown in the UI
    • suppressed_by    – pattern_id of a higher-ranked proposal that covers
                         this one (populated by the duplicate-suppression pass)
    """

    __tablename__ = "skill_proposals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow, nullable=False
    )

    # ── Pattern origin ────────────────────────────────────────────────────────
    pattern_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # ── Human-readable proposal content ───────────────────────────────────────
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # Machine-generated one-liner explaining why this was surfaced
    why_suggested: Mapped[str] = mapped_column(String(400), nullable=True)

    # Structured steps: list of {tool_name, command_template} dicts
    steps: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    # Benefit hints
    estimated_time_saved: Mapped[str] = mapped_column(String(80), nullable=True)

    # Risk inherited from the pattern
    risk_level: Mapped[str] = mapped_column(
        String(20), nullable=False, default="low"
    )  # low | medium | high | critical

    # ── Lifecycle status ──────────────────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="proposed"
    )  # proposed | approved | rejected

    # ── Soft-hide ────────────────────────────────────────────────────────────
    dismissed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # ── Back-reference to originating chains ─────────────────────────────────
    chain_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    # Pattern metadata for display
    frequency: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    confidence: Mapped[float] = mapped_column(Float, nullable=True)

    # ── Phase 6.5: User feedback signals ─────────────────────────────────────
    # Aggregate: +1 per 'useful', -1 per 'not_useful', average clamped [-1, 1]
    feedback_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    feedback_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_feedback_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, nullable=True
    )

    # ── Phase 6.5: Composite ranking ─────────────────────────────────────────
    # Pre-computed by rank_proposals(); higher → shown first
    relevance_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # ── Phase 6.5: Duplicate suppression ─────────────────────────────────────
    # Non-null when another proposal with a higher relevance_score covers this one
    suppressed_by: Mapped[str] = mapped_column(String(64), nullable=True)

    # ── Phase 10: Profile scoping ─────────────────────────────────────────────
    profile_id: Mapped[int] = mapped_column(Integer, nullable=True, index=True)
