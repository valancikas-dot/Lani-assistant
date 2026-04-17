"""
ORM model for Installed Skills (Phase 9 – Installed Skills Registry + Versioning).

An InstalledSkill is the live, managed entry for a skill that has been
fully approved and finalized from a SkillDraft.  It acts as the registry
record visible to the capability ecosystem.

Lifecycle
─────────
  installed   – active, may be invoked (through execution_guard)
  disabled    – temporarily inactive; cannot execute; preserved for re-enable
  superseded  – an older version that has been replaced by a newer install
  revoked     – permanently deactivated; cannot be re-enabled

Safety guarantees
─────────────────
• disabled / revoked skills must be rejected at execution time.
• Installation never auto-runs generated code.
• Every state change is auditable via updated_at + version history.
• The execution_guard is NOT modified by any installed-skill operation.
"""

import datetime
from sqlalchemy import Integer, String, Text, DateTime, JSON, Boolean, Float
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# Status constants
INSTALLED_STATUS_INSTALLED  = "installed"
INSTALLED_STATUS_DISABLED   = "disabled"
INSTALLED_STATUS_SUPERSEDED = "superseded"
INSTALLED_STATUS_REVOKED    = "revoked"

INSTALLED_STATUSES = [
    INSTALLED_STATUS_INSTALLED,
    INSTALLED_STATUS_DISABLED,
    INSTALLED_STATUS_SUPERSEDED,
    INSTALLED_STATUS_REVOKED,
]

# Terminal statuses that cannot be transitioned out of
TERMINAL_STATUSES = {INSTALLED_STATUS_SUPERSEDED, INSTALLED_STATUS_REVOKED}


class InstalledSkill(Base):
    """
    Registry entry for a fully-installed generated skill.

    One row per unique skill name.  Version history is stored in
    InstalledSkillVersion (separate table).
    """

    __tablename__ = "installed_skills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=True)

    # ── Identity ──────────────────────────────────────────────────────────────
    name: Mapped[str] = mapped_column(String(240), nullable=False, index=True, unique=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # ── Source lineage ────────────────────────────────────────────────────────
    source_draft_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    source_proposal_id: Mapped[int] = mapped_column(Integer, nullable=True)

    # ── Version tracking ──────────────────────────────────────────────────────
    current_version: Mapped[str] = mapped_column(String(32), nullable=False, default="1.0.0")
    # version number of the last installed state (for rollback reference)
    rollback_version: Mapped[str] = mapped_column(String(32), nullable=True)

    # ── Lifecycle ─────────────────────────────────────────────────────────────
    # installed | disabled | superseded | revoked
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=INSTALLED_STATUS_INSTALLED
    )

    # ── Execution gate ────────────────────────────────────────────────────────
    # enabled=False means the skill is not allowed to execute
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # ── Risk metadata (mirrors source draft) ──────────────────────────────────
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False, default="low")

    # ── Stored capability spec ────────────────────────────────────────────────
    # The scaffold/spec JSON from the approved draft, preserved for audit
    spec_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    scaffold_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # ── Usage tracking ────────────────────────────────────────────────────────
    last_used_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=True)
    use_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # ── Install timestamps ────────────────────────────────────────────────────
    installed_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=True)

    # ── Audit notes ───────────────────────────────────────────────────────────
    revoke_reason: Mapped[str] = mapped_column(Text, nullable=True)

    # ── Phase 10: Profile scoping ─────────────────────────────────────────────
    profile_id: Mapped[int] = mapped_column(Integer, nullable=True, index=True)
