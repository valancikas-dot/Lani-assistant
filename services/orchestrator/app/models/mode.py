"""
ORM models for the Mode System (Phase 11).

A Mode is a named operational context that biases which tools, capabilities,
and suggestions are surfaced to the user.  Modes are purely additive: they
enrich the LLM context and filter suggestion lists but never block tool access
or override execution_guard policies.

Built-in modes are seeded once at startup by mode_service.seed_builtin_modes().
Users may also create custom modes.

Tables
──────
modes         – mode catalogue (built-in + user-created)
user_modes    – many-to-many: which modes a given profile has activated

Lifecycle
─────────
  active   – mode is currently influencing context
  inactive – mode exists but is not contributing context
  archived – soft-deleted, hidden from selection UI
"""

from __future__ import annotations

import datetime
from typing import Optional, List

from sqlalchemy import Boolean, DateTime, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# ─── Status constants ──────────────────────────────────────────────────────────

MODE_STATUS_ACTIVE   = "active"
MODE_STATUS_INACTIVE = "inactive"
MODE_STATUS_ARCHIVED = "archived"

# ─── Category constants ────────────────────────────────────────────────────────

MODE_CATEGORY_PRODUCTIVITY  = "productivity"
MODE_CATEGORY_DEVELOPMENT   = "development"
MODE_CATEGORY_RESEARCH      = "research"
MODE_CATEGORY_CREATIVE       = "creative"
MODE_CATEGORY_COMMUNICATION = "communication"
MODE_CATEGORY_PERSONAL       = "personal"
MODE_CATEGORY_CUSTOM         = "custom"

MODE_CATEGORIES = [
    MODE_CATEGORY_PRODUCTIVITY,
    MODE_CATEGORY_DEVELOPMENT,
    MODE_CATEGORY_RESEARCH,
    MODE_CATEGORY_CREATIVE,
    MODE_CATEGORY_COMMUNICATION,
    MODE_CATEGORY_PERSONAL,
    MODE_CATEGORY_CUSTOM,
]

# ─── Built-in mode slug identifiers ──────────────────────────────────────────

BUILTIN_MODE_SLUGS: List[str] = [
    "developer",
    "researcher",
    "writer",
    "productivity",
    "communicator",
    "analyst",
    "student",
]


class Mode(Base):
    """
    A named operational context that adapts Lani's behaviour.

    Built-in modes cannot be deleted; they can only be deactivated or archived.
    """

    __tablename__ = "modes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow, nullable=False
    )
    updated_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime, nullable=True
    )

    # ── Identity ──────────────────────────────────────────────────────────────
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(
        String(40), nullable=False, default=MODE_CATEGORY_CUSTOM
    )
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Icon key for frontend rendering (maps to icon set in ModeSelector)
    icon: Mapped[str] = mapped_column(String(40), nullable=False, default="default")

    # Short tagline shown in onboarding card
    tagline: Mapped[str] = mapped_column(String(200), nullable=False, default="")

    # ── Classification ────────────────────────────────────────────────────────
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # ── Context injection ─────────────────────────────────────────────────────
    # Appended to the LLM system prompt when this mode is active.
    # Keep it short (≤ 200 tokens) and behaviour-focused.
    system_prompt_hint: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Ordered list of tool_name strings that are prioritised for this mode.
    # Does NOT block other tools — only influences suggestion ranking.
    preferred_tools: Mapped[list] = mapped_column(
        JSON, nullable=False, default=list
    )

    # Free-form capability tags used by ModeSuggestionService
    capability_tags: Mapped[list] = mapped_column(
        JSON, nullable=False, default=list
    )

    # ── Lifecycle ─────────────────────────────────────────────────────────────
    # active | inactive | archived
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=MODE_STATUS_INACTIVE
    )

    # ── Custom mode extra config ──────────────────────────────────────────────
    meta_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class UserMode(Base):
    """
    Junction table: which modes are active for a given profile.

    A NULL profile_id means the row belongs to the legacy / global context
    (pre-Phase-10 installs).
    """

    __tablename__ = "user_modes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow, nullable=False
    )

    # FK-like references (not enforced via ORM ForeignKey to keep migrations simple)
    profile_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, index=True
    )
    mode_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    # Whether this mode is currently active for this profile
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # When the user last toggled this mode
    toggled_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime, nullable=True
    )
