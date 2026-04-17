"""
Mode Service (Phase 11) – ModeManager.

Public API
──────────
seed_builtin_modes(db)
    Called on startup.  Creates the 7 built-in modes if they do not already
    exist.  Idempotent – safe to call every time the server starts.

list_modes(db, *, category, status, limit)
    Return all modes, optionally filtered.

get_mode(db, mode_id)
    Fetch a single Mode by id.

get_mode_by_slug(db, slug)
    Fetch a Mode by its slug.

get_active_modes(db, profile_id)
    Return all Mode objects that have an active UserMode row for the given
    profile.  profile_id=None → global / legacy context.

activate_mode(db, mode_id, profile_id)
    Create or update the UserMode junction row to is_active=True.

deactivate_mode(db, mode_id, profile_id)
    Set the UserMode junction row to is_active=False.

set_modes(db, mode_ids, profile_id)
    Atomically replace the full set of active modes for a profile.
    All other modes for that profile are deactivated.

create_custom_mode(db, *, name, description, icon, tagline,
                   system_prompt_hint, preferred_tools, capability_tags,
                   category, meta_json, profile_id)
    Create a user-defined mode.

build_mode_context_block(active_modes)
    Return a plain-text block ready to be appended to an LLM system prompt.
    Example:
      "Active modes: Developer, Researcher.
       Developer: Focus on code quality, debugging, and technical precision.
       Researcher: Favour deep research, source citation, and structured summaries."

mode_to_dict(mode, *, is_active)
    Serialise a Mode + activation state to a plain dict for API responses.
"""

from __future__ import annotations

import datetime
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mode import (
    Mode,
    UserMode,
    MODE_STATUS_ACTIVE,
    MODE_STATUS_INACTIVE,
    MODE_STATUS_ARCHIVED,
    MODE_CATEGORY_PRODUCTIVITY,
    MODE_CATEGORY_DEVELOPMENT,
    MODE_CATEGORY_RESEARCH,
    MODE_CATEGORY_CREATIVE,
    MODE_CATEGORY_COMMUNICATION,
    MODE_CATEGORY_PERSONAL,
    MODE_CATEGORY_CUSTOM,
)

log = logging.getLogger(__name__)


# ─── Built-in mode definitions ────────────────────────────────────────────────

_BUILTIN_MODES: List[Dict[str, Any]] = [
    {
        "slug": "developer",
        "name": "Developer",
        "category": MODE_CATEGORY_DEVELOPMENT,
        "icon": "code",
        "tagline": "Code, debug, and build software faster",
        "description": (
            "Activates code-centric tooling, prefers technical explanations, "
            "surfaces skill proposals related to automation and scripting."
        ),
        "system_prompt_hint": (
            "The user is in Developer mode. "
            "Prioritise code quality, debugging steps, and technical precision. "
            "Prefer concrete examples with code snippets. "
            "Suggest automations when detecting repetitive technical tasks."
        ),
        "preferred_tools": [
            "create_file", "read_document", "operator_open_app",
            "web_search", "chat",
        ],
        "capability_tags": ["code", "debug", "build", "script", "automation"],
    },
    {
        "slug": "researcher",
        "name": "Researcher",
        "category": MODE_CATEGORY_RESEARCH,
        "icon": "search",
        "tagline": "Deep research, structured summaries, source tracking",
        "description": (
            "Favours deep research, citation, and structured note-taking. "
            "Skill proposals lean toward information distillation automations."
        ),
        "system_prompt_hint": (
            "The user is in Researcher mode. "
            "Prioritise thorough, well-sourced answers. "
            "Structure responses with headings, bullet points, and references. "
            "When web content is fetched, always summarise key findings."
        ),
        "preferred_tools": [
            "research_and_prepare_brief", "web_search", "summarize_document",
            "save_memory", "chat",
        ],
        "capability_tags": ["research", "search", "summarise", "notes", "sources"],
    },
    {
        "slug": "writer",
        "name": "Writer",
        "category": MODE_CATEGORY_CREATIVE,
        "icon": "pen",
        "tagline": "Draft, edit, and polish written content",
        "description": (
            "Tailors Lani toward content creation: drafting, editing, "
            "proofreading, and creative writing."
        ),
        "system_prompt_hint": (
            "The user is in Writer mode. "
            "Focus on clarity, tone, grammar, and readability. "
            "Offer to improve or restructure text when the user shares drafts. "
            "Suggest document operations (create, read, summarise) proactively."
        ),
        "preferred_tools": [
            "create_file", "read_document", "summarize_document", "chat",
        ],
        "capability_tags": ["writing", "editing", "drafting", "content", "creative"],
    },
    {
        "slug": "productivity",
        "name": "Productivity",
        "category": MODE_CATEGORY_PRODUCTIVITY,
        "icon": "check",
        "tagline": "Organise tasks, files, and workflows",
        "description": (
            "Optimises for task execution, file management, and workflow "
            "automation.  Favours action-oriented, concise responses."
        ),
        "system_prompt_hint": (
            "The user is in Productivity mode. "
            "Be concise and action-oriented. "
            "Prioritise completing tasks over explaining them. "
            "Suggest file organisation and workflow automations when relevant."
        ),
        "preferred_tools": [
            "create_folder", "move_file", "sort_downloads",
            "operator_open_app", "operator_press_shortcut",
            "save_memory", "chat",
        ],
        "capability_tags": [
            "tasks", "files", "organisation", "automation", "workflow",
        ],
    },
    {
        "slug": "communicator",
        "name": "Communicator",
        "category": MODE_CATEGORY_COMMUNICATION,
        "icon": "message",
        "tagline": "Email, messaging, and social media workflows",
        "description": (
            "Focuses on communication tasks: composing emails, managing "
            "messages, and social media actions."
        ),
        "system_prompt_hint": (
            "The user is in Communicator mode. "
            "Prioritise clear, professional, and friendly communication. "
            "Help compose, edit, and schedule messages and emails."
        ),
        "preferred_tools": [
            "safari_open", "operator_open_app", "chat",
        ],
        "capability_tags": [
            "email", "messaging", "social", "communication", "compose",
        ],
    },
    {
        "slug": "analyst",
        "name": "Analyst",
        "category": MODE_CATEGORY_PRODUCTIVITY,
        "icon": "chart",
        "tagline": "Data analysis, spreadsheets, and metrics",
        "description": (
            "Enables data-centric workflows: spreadsheet operations, metrics "
            "tracking, and analytical reasoning."
        ),
        "system_prompt_hint": (
            "The user is in Analyst mode. "
            "Favour structured, data-driven answers. "
            "When numbers or spreadsheets are involved, reason step-by-step. "
            "Offer to summarise or compute when data is presented."
        ),
        "preferred_tools": [
            "read_document", "summarize_document", "web_search",
            "safari_open", "chat",
        ],
        "capability_tags": [
            "data", "analysis", "spreadsheets", "metrics", "numbers",
        ],
    },
    {
        "slug": "student",
        "name": "Student",
        "category": MODE_CATEGORY_PERSONAL,
        "icon": "book",
        "tagline": "Learning, study notes, and concept explanations",
        "description": (
            "Tuned for learning: thorough explanations, concept breakdowns, "
            "flash-card style summaries, and study automation."
        ),
        "system_prompt_hint": (
            "The user is in Student mode. "
            "Explain concepts from first principles. "
            "Use analogies, examples, and simple language. "
            "Offer to create study notes or summaries."
        ),
        "preferred_tools": [
            "web_search", "research_and_prepare_brief",
            "save_memory", "create_file", "chat",
        ],
        "capability_tags": [
            "learning", "study", "education", "notes", "explanation",
        ],
    },
]


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _now() -> datetime.datetime:
    return datetime.datetime.utcnow()


async def _get_user_mode_row(
    db: AsyncSession, mode_id: int, profile_id: Optional[int]
) -> Optional[UserMode]:
    q = select(UserMode).where(
        UserMode.mode_id == mode_id,
        UserMode.profile_id == profile_id,
    )
    result = await db.execute(q)
    return result.scalar_one_or_none()


# ─── Public API ───────────────────────────────────────────────────────────────

async def seed_builtin_modes(db: AsyncSession) -> None:
    """
    Idempotently create the 7 built-in modes.

    Uses slug as the uniqueness key.  Existing rows are left untouched so that
    user edits (e.g. custom system_prompt_hint) survive restarts.
    """
    existing_q = await db.execute(select(Mode.slug))
    existing_slugs = {row[0] for row in existing_q.all()}

    added = 0
    for defn in _BUILTIN_MODES:
        if defn["slug"] in existing_slugs:
            continue
        mode = Mode(
            slug=defn["slug"],
            name=defn["name"],
            category=defn["category"],
            icon=defn["icon"],
            tagline=defn["tagline"],
            description=defn["description"],
            system_prompt_hint=defn["system_prompt_hint"],
            preferred_tools=defn["preferred_tools"],
            capability_tags=defn["capability_tags"],
            status=MODE_STATUS_INACTIVE,
            is_builtin=True,
            meta_json={},
            created_at=_now(),
        )
        db.add(mode)
        added += 1

    if added:
        await db.flush()
        log.info("[mode] seeded %d built-in modes", added)


async def list_modes(
    db: AsyncSession,
    *,
    category: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
) -> List[Mode]:
    """Return modes, optionally filtered by category and/or status."""
    q = select(Mode)
    if category:
        q = q.where(Mode.category == category)
    if status:
        q = q.where(Mode.status == status)
    q = q.order_by(Mode.is_builtin.desc(), Mode.name).limit(limit)
    result = await db.execute(q)
    return list(result.scalars().all())


async def get_mode(db: AsyncSession, mode_id: int) -> Optional[Mode]:
    result = await db.execute(select(Mode).where(Mode.id == mode_id))
    return result.scalar_one_or_none()


async def get_mode_by_slug(db: AsyncSession, slug: str) -> Optional[Mode]:
    result = await db.execute(select(Mode).where(Mode.slug == slug))
    return result.scalar_one_or_none()


async def get_active_modes(
    db: AsyncSession,
    profile_id: Optional[int] = None,
) -> List[Mode]:
    """Return all Mode objects currently active for *profile_id*."""
    um_q = select(UserMode.mode_id).where(
        UserMode.profile_id == profile_id,
        UserMode.is_active.is_(True),
    )
    um_result = await db.execute(um_q)
    active_ids = [row[0] for row in um_result.all()]
    if not active_ids:
        return []
    mode_q = select(Mode).where(Mode.id.in_(active_ids))
    mode_result = await db.execute(mode_q)
    return list(mode_result.scalars().all())


async def activate_mode(
    db: AsyncSession,
    mode_id: int,
    profile_id: Optional[int] = None,
) -> Optional[Mode]:
    """
    Activate *mode_id* for *profile_id*.

    Creates the UserMode junction row if it does not exist.
    Returns the Mode object, or None if the mode does not exist.
    """
    mode = await get_mode(db, mode_id)
    if mode is None:
        return None
    if mode.status == MODE_STATUS_ARCHIVED:
        return None

    um = await _get_user_mode_row(db, mode_id, profile_id)
    if um is None:
        um = UserMode(
            mode_id=mode_id,
            profile_id=profile_id,
            is_active=True,
            created_at=_now(),
            toggled_at=_now(),
        )
        db.add(um)
    else:
        um.is_active = True
        um.toggled_at = _now()

    # Mirror status on the Mode row itself (for cross-profile queries)
    mode.status = MODE_STATUS_ACTIVE
    mode.updated_at = _now()
    await db.flush()
    log.info("[mode] activated mode '%s' for profile_id=%s", mode.slug, profile_id)
    return mode


async def deactivate_mode(
    db: AsyncSession,
    mode_id: int,
    profile_id: Optional[int] = None,
) -> Optional[Mode]:
    """
    Deactivate *mode_id* for *profile_id*.
    Returns the Mode object, or None if the mode does not exist.
    """
    mode = await get_mode(db, mode_id)
    if mode is None:
        return None

    um = await _get_user_mode_row(db, mode_id, profile_id)
    if um is not None:
        um.is_active = False
        um.toggled_at = _now()
        await db.flush()

    # Check if any profile still has this mode active before clearing global status
    still_active_q = select(UserMode).where(
        UserMode.mode_id == mode_id,
        UserMode.is_active.is_(True),
    )
    still = (await db.execute(still_active_q)).scalar_one_or_none()
    if still is None:
        mode.status = MODE_STATUS_INACTIVE
        mode.updated_at = _now()

    await db.flush()
    log.info("[mode] deactivated mode '%s' for profile_id=%s", mode.slug, profile_id)
    return mode


async def set_modes(
    db: AsyncSession,
    mode_ids: List[int],
    profile_id: Optional[int] = None,
) -> List[Mode]:
    """
    Atomically replace the full set of active modes for *profile_id*.

    All UserMode rows for this profile are set to is_active=False, then each
    mode in *mode_ids* is activated.  Returns the list of active Mode objects.
    """
    # Deactivate all current modes for this profile
    deactivate_stmt = (
        update(UserMode)
        .where(UserMode.profile_id == profile_id)
        .values(is_active=False, toggled_at=_now())
    )
    await db.execute(deactivate_stmt)
    await db.flush()

    active: List[Mode] = []
    for mid in mode_ids:
        mode = await activate_mode(db, mid, profile_id)
        if mode is not None:
            active.append(mode)

    log.info(
        "[mode] set_modes: profile_id=%s, active=%s",
        profile_id, [m.slug for m in active],
    )
    return active


async def create_custom_mode(
    db: AsyncSession,
    *,
    name: str,
    description: str = "",
    icon: str = "default",
    tagline: str = "",
    system_prompt_hint: str = "",
    preferred_tools: Optional[List[str]] = None,
    capability_tags: Optional[List[str]] = None,
    category: str = MODE_CATEGORY_CUSTOM,
    meta_json: Optional[Dict[str, Any]] = None,
) -> Mode:
    """Create a user-defined mode.  Returns the new Mode (not yet committed)."""
    # Derive slug from name
    import re
    slug_base = re.sub(r"[^a-z0-9]+", "-", name.lower().strip()).strip("-")
    existing = await db.execute(select(Mode.slug).where(Mode.slug.like(f"{slug_base}%")))
    taken = {row[0] for row in existing.all()}
    slug = slug_base
    if slug in taken:
        counter = 2
        while f"{slug_base}-{counter}" in taken:
            counter += 1
        slug = f"{slug_base}-{counter}"

    mode = Mode(
        slug=slug,
        name=name,
        category=category,
        icon=icon,
        tagline=tagline,
        description=description,
        system_prompt_hint=system_prompt_hint,
        preferred_tools=preferred_tools or [],
        capability_tags=capability_tags or [],
        status=MODE_STATUS_INACTIVE,
        is_builtin=False,
        meta_json=meta_json or {},
        created_at=_now(),
    )
    db.add(mode)
    await db.flush()
    log.info("[mode] created custom mode '%s' (slug=%s)", name, slug)
    return mode


def build_mode_context_block(active_modes: List[Mode]) -> str:
    """
    Build the LLM context block to append to the system prompt.

    Returns an empty string when no modes are active.
    """
    if not active_modes:
        return ""
    names = ", ".join(m.name for m in active_modes)
    hints = "\n".join(
        f"• {m.name}: {m.system_prompt_hint}"
        for m in active_modes
        if m.system_prompt_hint
    )
    block = f"\n\n━━ ACTIVE MODES: {names} ━━\n{hints}"
    return block


def mode_to_dict(mode: Mode, *, is_active: bool = False) -> Dict[str, Any]:
    """Serialise a Mode to a dict for API responses."""
    return {
        "id": mode.id,
        "slug": mode.slug,
        "name": mode.name,
        "category": mode.category,
        "icon": mode.icon,
        "tagline": mode.tagline,
        "description": mode.description,
        "is_builtin": mode.is_builtin,
        "status": mode.status,
        "system_prompt_hint": mode.system_prompt_hint,
        "preferred_tools": mode.preferred_tools,
        "capability_tags": mode.capability_tags,
        "meta_json": mode.meta_json,
        "is_active": is_active,
        "created_at": mode.created_at.isoformat() if mode.created_at else None,
        "updated_at": mode.updated_at.isoformat() if mode.updated_at else None,
    }
