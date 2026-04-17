"""
ORM model for Skill Drafts (Phase 7 – Proposal → Skill Scaffold Generator).

A SkillDraft is the artefact produced when an approved SkillProposal is
converted into an inspectable, non-executing automation definition.

Lifecycle
─────────
  draft       – generated, not yet tested
  tested      – sandbox test has been run (see test_report)
  approved    – user has approved for installation
  installed   – marked as installed (record-only; nothing auto-executes)
  discarded   – user discarded the draft

Safety guarantees
─────────────────
• Generation never executes anything.
• Testing runs in a pure-Python simulation sandbox only.
• Installation only updates this row's status + creates an approval_request.
• execution_guard is NOT modified by any draft operation.
"""

import datetime
from sqlalchemy import Integer, String, Text, DateTime, JSON, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SkillDraft(Base):
    """
    A generated, inspectable automation draft derived from a SkillProposal.
    """

    __tablename__ = "skill_drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow, nullable=False
    )

    # ── Origin ────────────────────────────────────────────────────────────────
    proposal_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    # ── Identity ──────────────────────────────────────────────────────────────
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # ── Spec (SkillSpec serialised as JSON) ───────────────────────────────────
    spec_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # ── Scaffold ──────────────────────────────────────────────────────────────
    scaffold_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # "json_workflow" | "python_stub" | "yaml_workflow"
    scaffold_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="json_workflow"
    )

    # ── Risk ──────────────────────────────────────────────────────────────────
    risk_level: Mapped[str] = mapped_column(
        String(20), nullable=False, default="low"
    )

    # ── Lifecycle ─────────────────────────────────────────────────────────────
    # draft | tested | approved | installed | discarded
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft"
    )

    # ── Sandbox test report (set after POST /test) ────────────────────────────
    test_report: Mapped[dict] = mapped_column(JSON, nullable=True)
    tested_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=True)

    # ── Approval + install tracking ───────────────────────────────────────────
    approval_request_id: Mapped[int] = mapped_column(Integer, nullable=True)
    installed_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=True)

    # ── Flags ─────────────────────────────────────────────────────────────────
    # True once the user has explicitly reviewed the scaffold
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # ── Phase 10: Profile scoping ─────────────────────────────────────────────
    profile_id: Mapped[int] = mapped_column(Integer, nullable=True, index=True)
