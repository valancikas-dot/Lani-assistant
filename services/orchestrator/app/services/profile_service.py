"""
Profile Service (Phase 10 – Multi-profile / Team Mode).

Public API
──────────
  create_profile          – create a new workspace profile
  list_profiles           – list all profiles
  get_profile             – fetch a single profile by id
  get_profile_by_slug     – fetch by URL-safe slug
  activate_profile        – mark one profile as active, deactivate others
  get_active_profile      – return the currently-active profile
  get_or_create_default   – return (or lazily create) the "default" profile
  update_profile          – patch name / description / security mode / meta
  archive_profile         – soft-delete (status → archived, is_active → False)
  profile_to_dict         – ORM row → serialisable dict
  get_profile_stats       – per-profile counts of missions / skills / proposals

Scope isolation helpers
───────────────────────
  assert_profile_owns_mission        – raises ValueError on cross-profile access
  assert_profile_owns_installed_skill

Design choices
──────────────
• is_active is a single-row flag: only ONE profile is active at a time.
  When ``activate_profile`` is called, all other profiles are flipped to
  ``is_active=False`` in one UPDATE before setting the target to True.
• The "default" profile is auto-created on first startup so legacy data
  (rows without profile_id) still has a named home.
• profile_id is stored on the *child* entity rows.  The Profile table itself
  has no FK back to children – avoiding cascade issues.
"""

from __future__ import annotations

import datetime
import logging
import re
from typing import Any, Dict, List, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.profile import (
    Profile,
    PROFILE_STATUS_ACTIVE,
    PROFILE_STATUS_INACTIVE,
    PROFILE_STATUS_ARCHIVED,
    PROFILE_TYPE_PERSONAL,
)

log = logging.getLogger(__name__)

DEFAULT_PROFILE_NAME = "Default"
DEFAULT_PROFILE_SLUG = "default"


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _now() -> datetime.datetime:
    return datetime.datetime.utcnow()


def _slugify(name: str) -> str:
    """Convert a profile name to a URL-safe slug."""
    slug = name.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "profile"


async def _deactivate_all(db: AsyncSession) -> None:
    """Set is_active=False on every profile (used before activating one)."""
    await db.execute(
        update(Profile).values(is_active=False, updated_at=_now())
    )


# ─── Public API ───────────────────────────────────────────────────────────────

async def create_profile(
    db: AsyncSession,
    *,
    name: str,
    profile_type: str = PROFILE_TYPE_PERSONAL,
    description: str = "",
    default_security_mode: str = "standard",
    meta_json: Optional[Dict[str, Any]] = None,
    activate: bool = False,
) -> Profile:
    """
    Create a new profile.

    Parameters
    ----------
    name:
        Human-readable name.  Must be unique.
    profile_type:
        "personal" | "work" | "team"
    description:
        Optional prose description.
    default_security_mode:
        "standard" | "strict" | "permissive"
    meta_json:
        Arbitrary per-profile settings dict.
    activate:
        If True, immediately set this profile as the active one.

    Returns
    -------
    The newly created Profile ORM object (not yet committed – caller commits).
    """
    slug = _slugify(name)
    # Ensure slug uniqueness by appending a counter when needed
    async with db.begin_nested():
        existing_slugs_q = select(Profile.slug).where(Profile.slug.like(f"{slug}%"))
        result = await db.execute(existing_slugs_q)
        taken = {row[0] for row in result.all()}
    if slug in taken:
        counter = 2
        while f"{slug}-{counter}" in taken:
            counter += 1
        slug = f"{slug}-{counter}"

    if activate:
        await _deactivate_all(db)

    profile = Profile(
        name=name,
        slug=slug,
        profile_type=profile_type,
        status=PROFILE_STATUS_ACTIVE,
        is_active=activate,
        description=description,
        default_security_mode=default_security_mode,
        meta_json=meta_json or {},
        created_at=_now(),
    )
    db.add(profile)
    await db.flush()
    log.info("[profile] created profile '%s' (id=%s, activate=%s)", name, profile.id, activate)
    return profile


async def list_profiles(
    db: AsyncSession,
    *,
    status: Optional[str] = None,
    limit: int = 100,
) -> List[Profile]:
    """
    List profiles, optionally filtered by status.

    Sorted by created_at ascending (oldest first).
    """
    q = select(Profile).order_by(Profile.created_at.asc()).limit(limit)
    if status:
        q = q.where(Profile.status == status)
    result = await db.execute(q)
    return list(result.scalars().all())


async def get_profile(db: AsyncSession, profile_id: int) -> Optional[Profile]:
    """Fetch a single profile by primary key."""
    return await db.get(Profile, profile_id)


async def get_profile_by_slug(db: AsyncSession, slug: str) -> Optional[Profile]:
    """Fetch a single profile by slug."""
    result = await db.execute(select(Profile).where(Profile.slug == slug))
    return result.scalar_one_or_none()


async def get_active_profile(db: AsyncSession) -> Optional[Profile]:
    """Return the currently active profile, or None if no profile is active."""
    result = await db.execute(
        select(Profile).where(Profile.is_active == True)  # noqa: E712
    )
    return result.scalar_one_or_none()


async def activate_profile(db: AsyncSession, profile_id: int) -> Optional[Profile]:
    """
    Make profile *profile_id* the active one.

    Deactivates all other profiles first (is_active=False), then sets
    the target profile to is_active=True.

    Returns the activated Profile, or None if not found / archived.
    """
    profile = await get_profile(db, profile_id)
    if profile is None:
        log.warning("[profile] activate: profile %s not found", profile_id)
        return None
    if profile.status == PROFILE_STATUS_ARCHIVED:
        log.warning(
            "[profile] activate: refusing to activate archived profile %s", profile_id
        )
        return None

    await _deactivate_all(db)
    profile.is_active = True
    profile.status = PROFILE_STATUS_ACTIVE
    profile.updated_at = _now()
    log.info("[profile] activated profile '%s' (id=%s)", profile.name, profile.id)
    return profile


async def get_or_create_default(db: AsyncSession) -> Profile:
    """
    Return the default profile, creating it (and activating it) if it doesn't
    exist.  Called on startup to ensure legacy data has a home.
    """
    existing = await get_profile_by_slug(db, DEFAULT_PROFILE_SLUG)
    if existing is not None:
        return existing

    log.info("[profile] creating default profile")
    profile = await create_profile(
        db,
        name=DEFAULT_PROFILE_NAME,
        profile_type=PROFILE_TYPE_PERSONAL,
        description="Default workspace (auto-created on startup)",
        activate=True,
    )
    await db.commit()
    return profile


async def update_profile(
    db: AsyncSession,
    profile_id: int,
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
    default_security_mode: Optional[str] = None,
    meta_json: Optional[Dict[str, Any]] = None,
) -> Optional[Profile]:
    """Patch editable fields on a profile."""
    profile = await get_profile(db, profile_id)
    if profile is None:
        return None
    if name is not None:
        profile.name = name
        profile.slug = _slugify(name)
    if description is not None:
        profile.description = description
    if default_security_mode is not None:
        profile.default_security_mode = default_security_mode
    if meta_json is not None:
        profile.meta_json = meta_json
    profile.updated_at = _now()
    return profile


async def archive_profile(db: AsyncSession, profile_id: int) -> Optional[Profile]:
    """
    Archive a profile (soft-delete).  Archived profiles cannot be activated.
    If it is currently active, no profile will be active after this call.
    """
    profile = await get_profile(db, profile_id)
    if profile is None:
        return None
    profile.status = PROFILE_STATUS_ARCHIVED
    profile.is_active = False
    profile.updated_at = _now()
    log.info("[profile] archived profile '%s' (id=%s)", profile.name, profile.id)
    return profile


async def get_profile_stats(
    db: AsyncSession,
    profile_id: int,
) -> Dict[str, int]:
    """
    Return counts of scoped entities for this profile.

    Uses raw COUNT queries so it stays fast even with large tables.
    Entities without profile_id support are counted globally (0 means
    'not yet scoped').
    """
    from sqlalchemy import func, text as _text

    async def _count(table: str) -> int:
        try:
            r = await db.execute(
                _text(f"SELECT COUNT(*) FROM {table} WHERE profile_id = :pid"),
                {"pid": profile_id},
            )
            return r.scalar() or 0
        except Exception:
            return 0

    missions         = await _count("missions")
    proposals        = await _count("skill_proposals")
    drafts           = await _count("skill_drafts")
    installed_skills = await _count("installed_skills")
    approvals        = await _count("approval_requests")

    return {
        "missions":         missions,
        "skill_proposals":  proposals,
        "skill_drafts":     drafts,
        "installed_skills": installed_skills,
        "approvals":        approvals,
    }


# ─── Scope-isolation assertions ───────────────────────────────────────────────

def assert_profile_scope(entity_profile_id: Optional[int], caller_profile_id: int, entity_label: str = "entity") -> None:
    """
    Raise ValueError if an entity's profile_id does not match the caller's.

    Entities with profile_id=None are legacy global rows; they pass the check
    to preserve backward compatibility.
    """
    if entity_profile_id is None:
        return  # legacy global row – no restriction
    if entity_profile_id != caller_profile_id:
        raise ValueError(
            f"Cross-profile access denied: {entity_label} belongs to profile "
            f"{entity_profile_id} but caller is profile {caller_profile_id}"
        )


# ─── Serialiser ──────────────────────────────────────────────────────────────

def profile_to_dict(profile: Profile, stats: Optional[Dict[str, int]] = None) -> Dict[str, Any]:
    """Serialise a Profile ORM row to a JSON-safe dict."""
    d: Dict[str, Any] = {
        "id":                   profile.id,
        "name":                 profile.name,
        "slug":                 profile.slug,
        "profile_type":         profile.profile_type,
        "status":               profile.status,
        "is_active":            profile.is_active,
        "description":          profile.description,
        "default_security_mode": profile.default_security_mode,
        "meta_json":            profile.meta_json or {},
        "created_at":           profile.created_at.isoformat() if profile.created_at else None,
        "updated_at":           profile.updated_at.isoformat() if profile.updated_at else None,
    }
    if stats is not None:
        d["stats"] = stats
    return d
