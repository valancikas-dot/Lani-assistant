"""
ORM model for Installed Skill Version History (Phase 9).

Each time a skill is upgraded or rolled back, a new InstalledSkillVersion
row is appended.  This gives a full, immutable audit trail of what was
active at each point in time.
"""

import datetime
from sqlalchemy import Integer, String, Text, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class InstalledSkillVersion(Base):
    """
    Immutable version-history record for an InstalledSkill.

    One row per install/upgrade/rollback event.
    """

    __tablename__ = "installed_skill_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow, nullable=False
    )

    # ── Parent ────────────────────────────────────────────────────────────────
    skill_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    skill_name: Mapped[str] = mapped_column(String(240), nullable=False)

    # ── Version metadata ──────────────────────────────────────────────────────
    version: Mapped[str] = mapped_column(String(32), nullable=False)

    # ── Action that created this record ──────────────────────────────────────
    # install | upgrade | rollback | disable | enable | revoke
    action: Mapped[str] = mapped_column(String(32), nullable=False)

    # ── Source draft at this version ──────────────────────────────────────────
    source_draft_id: Mapped[int] = mapped_column(Integer, nullable=False)

    # ── Snapshot of the spec/scaffold at this version ─────────────────────────
    spec_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    scaffold_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # ── Risk level at this version ────────────────────────────────────────────
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False, default="low")

    # ── Optional note ─────────────────────────────────────────────────────────
    note: Mapped[str] = mapped_column(Text, nullable=True)
