"""
ORM model for Profiles / Workspaces (Phase 10 – Multi-profile / Team Mode).

A Profile is an isolated workspace.  Every entity that carries a
``profile_id`` column belongs exclusively to that profile; queries for
missions, proposals, drafts, installed skills, and approvals are always
filtered by ``profile_id`` so there is no cross-workspace data leakage.

Lifecycle
─────────
  active    – currently usable; can be set as the "current" profile
  inactive  – preserved but not selectable without explicit reactivation
  archived  – read-only historical record; cannot be switched to

Safety guarantees
─────────────────
• Profiles do NOT bypass execution_guard.
• Sessions from one profile are not reusable by another profile.
• Installed skills are profile-scoped; an installed skill in profile A is
  NOT visible or executable from profile B.
• All state-changing actions remain auditable with profile_id context.
"""

import datetime
from sqlalchemy import Integer, String, Text, DateTime, JSON, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# ── Status constants ──────────────────────────────────────────────────────────

PROFILE_STATUS_ACTIVE   = "active"
PROFILE_STATUS_INACTIVE = "inactive"
PROFILE_STATUS_ARCHIVED = "archived"

PROFILE_STATUSES = [
    PROFILE_STATUS_ACTIVE,
    PROFILE_STATUS_INACTIVE,
    PROFILE_STATUS_ARCHIVED,
]

# ── Type constants ────────────────────────────────────────────────────────────

PROFILE_TYPE_PERSONAL = "personal"
PROFILE_TYPE_WORK     = "work"
PROFILE_TYPE_TEAM     = "team"

PROFILE_TYPES = [
    PROFILE_TYPE_PERSONAL,
    PROFILE_TYPE_WORK,
    PROFILE_TYPE_TEAM,
]


class Profile(Base):
    """
    An isolated workspace / profile.

    One row per workspace.  The "default" profile is created automatically
    on first startup so that all pre-existing data (missions, skills, etc.)
    belongs to a named profile rather than an unnamed void.
    """

    __tablename__ = "profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=True)

    # ── Identity ──────────────────────────────────────────────────────────────
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)

    # URL-safe slug derived from name (e.g. "my-work")
    slug: Mapped[str] = mapped_column(String(120), nullable=False, unique=True, index=True)

    # personal | work | team
    profile_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default=PROFILE_TYPE_PERSONAL
    )

    # ── Lifecycle ─────────────────────────────────────────────────────────────
    # active | inactive | archived
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=PROFILE_STATUS_ACTIVE
    )

    # Whether this profile is the "selected" one in the UI
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # ── Policy defaults ───────────────────────────────────────────────────────
    # "standard" | "strict" | "permissive"
    default_security_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, default="standard"
    )

    # ── Display ───────────────────────────────────────────────────────────────
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Arbitrary per-profile settings / feature flags (UI colour, avatar, etc.)
    meta_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
