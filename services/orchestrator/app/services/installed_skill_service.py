"""
Installed Skill Service – Phase 9: Installed Skills Registry + Versioning.

Manages the full lifecycle of installed generated skills:

  finalize_install  – turn an approved SkillDraft into an InstalledSkill
  enable_skill      – re-activate a disabled skill
  disable_skill     – temporarily block execution
  revoke_skill      – permanently deactivate (no re-enable)
  rollback_skill    – revert to previous version snapshot
  upgrade_skill     – install a newer draft on top of an existing skill
  get_skill         – fetch by id
  get_skill_by_name – fetch by name (for execution gate lookups)
  list_skills       – paginated list with optional status filter
  get_version_history – list all InstalledSkillVersion rows for a skill
  is_skill_executable – safety gate: True only if installed + enabled

Safety guarantees
─────────────────
• disabled / revoked skills: is_skill_executable() returns False.
• finalize_install checks that the linked ApprovalRequest is "approved"
  before creating any registry entry.
• No code is executed – no subprocess, no eval.
• Every state transition records an InstalledSkillVersion row for audit.
"""

from __future__ import annotations

import datetime
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approval_request import ApprovalRequest
from app.models.installed_skill import (
    InstalledSkill,
    INSTALLED_STATUS_INSTALLED,
    INSTALLED_STATUS_DISABLED,
    INSTALLED_STATUS_REVOKED,
    INSTALLED_STATUS_SUPERSEDED,
    TERMINAL_STATUSES,
)
from app.models.installed_skill_version import InstalledSkillVersion
from app.models.skill_draft import SkillDraft

log = logging.getLogger(__name__)


# ─── Semver helper ────────────────────────────────────────────────────────────

def _bump_minor(version: str) -> str:
    """
    Increment the minor component of a semver string.

    "1.0.0" → "1.1.0",  "2.3.0" → "2.4.0"
    Falls back to "<version>+1" if parsing fails.
    """
    try:
        parts = version.split(".")
        parts[1] = str(int(parts[1]) + 1)
        return ".".join(parts)
    except Exception:
        return f"{version}+1"


# ─── Serialisers ─────────────────────────────────────────────────────────────

def skill_to_dict(skill: InstalledSkill) -> Dict[str, Any]:
    """Serialise an InstalledSkill ORM row → plain dict for API responses."""
    return {
        "id": skill.id,
        "name": skill.name,
        "description": skill.description,
        "source_draft_id": skill.source_draft_id,
        "source_proposal_id": skill.source_proposal_id,
        "current_version": skill.current_version,
        "rollback_version": skill.rollback_version,
        "status": skill.status,
        "enabled": skill.enabled,
        "risk_level": skill.risk_level,
        "spec_json": skill.spec_json,
        "scaffold_json": skill.scaffold_json,
        "last_used_at": skill.last_used_at.isoformat() if skill.last_used_at else None,
        "use_count": skill.use_count,
        "installed_at": skill.installed_at.isoformat() if skill.installed_at else None,
        "revoke_reason": skill.revoke_reason,
        "created_at": skill.created_at.isoformat() if skill.created_at else None,
        "updated_at": skill.updated_at.isoformat() if skill.updated_at else None,
    }


def version_to_dict(v: InstalledSkillVersion) -> Dict[str, Any]:
    """Serialise an InstalledSkillVersion row → plain dict."""
    return {
        "id": v.id,
        "skill_id": v.skill_id,
        "skill_name": v.skill_name,
        "version": v.version,
        "action": v.action,
        "source_draft_id": v.source_draft_id,
        "spec_json": v.spec_json,
        "scaffold_json": v.scaffold_json,
        "risk_level": v.risk_level,
        "note": v.note,
        "created_at": v.created_at.isoformat() if v.created_at else None,
    }


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _now() -> datetime.datetime:
    return datetime.datetime.utcnow()


def _append_version(
    skill: InstalledSkill,
    action: str,
    draft: Optional[SkillDraft] = None,
    note: Optional[str] = None,
) -> InstalledSkillVersion:
    """Create a new version history row for *skill*."""
    return InstalledSkillVersion(
        skill_id=skill.id,
        skill_name=skill.name,
        version=skill.current_version,
        action=action,
        source_draft_id=draft.id if draft else skill.source_draft_id,
        spec_json=skill.spec_json or {},
        scaffold_json=skill.scaffold_json or {},
        risk_level=skill.risk_level,
        note=note,
    )


async def _load_draft(db: AsyncSession, draft_id: int) -> Optional[SkillDraft]:
    result = await db.execute(select(SkillDraft).where(SkillDraft.id == draft_id))
    return result.scalar_one_or_none()


async def _load_approval(db: AsyncSession, approval_id: int) -> Optional[ApprovalRequest]:
    result = await db.execute(
        select(ApprovalRequest).where(ApprovalRequest.id == approval_id)
    )
    return result.scalar_one_or_none()


async def _find_by_name(db: AsyncSession, name: str) -> Optional[InstalledSkill]:
    result = await db.execute(
        select(InstalledSkill).where(InstalledSkill.name == name)
    )
    return result.scalar_one_or_none()


# ─── Public API ───────────────────────────────────────────────────────────────

async def finalize_install(
    db: AsyncSession,
    draft_id: int,
) -> Optional[InstalledSkill]:
    """
    Finalize installation: turn an approved SkillDraft into an InstalledSkill.

    Pre-conditions (any failure returns None with a logged reason):
    • Draft with *draft_id* must exist.
    • Draft.status must be "install_requested".
    • Draft.approval_request_id must point to an approved ApprovalRequest.

    If an InstalledSkill with the same name already exists and is not in a
    terminal state (revoked/superseded), this performs an **upgrade**:
    the existing record's current_version is saved as rollback_version, the
    version is bumped, and the old record is updated in-place (no duplicate
    rows).

    In both cases an InstalledSkillVersion row is appended for the audit log,
    and draft.status is set to "installed".
    """
    draft = await _load_draft(db, draft_id)
    if draft is None:
        log.warning("[skill] finalize_install: draft %s not found", draft_id)
        return None

    if draft.status != "install_requested":
        log.warning(
            "[skill] finalize_install: draft %s has status=%s, expected install_requested",
            draft_id,
            draft.status,
        )
        return None

    if not draft.approval_request_id:
        log.warning("[skill] finalize_install: draft %s has no approval_request_id", draft_id)
        return None

    approval = await _load_approval(db, draft.approval_request_id)
    if approval is None or approval.status != "approved":
        log.warning(
            "[skill] finalize_install: draft %s approval %s not approved (status=%s)",
            draft_id,
            draft.approval_request_id,
            approval.status if approval else "missing",
        )
        return None

    now = _now()
    existing = await _find_by_name(db, draft.name)

    if existing is not None and existing.status not in TERMINAL_STATUSES:
        # ── Upgrade path ─────────────────────────────────────────────────────
        old_version = existing.current_version
        new_version = _bump_minor(old_version)
        log.info(
            "[skill] upgrading '%s': %s → %s (draft %s)",
            draft.name,
            old_version,
            new_version,
            draft_id,
        )
        existing.rollback_version = old_version
        existing.current_version = new_version
        existing.source_draft_id = draft_id
        existing.description = draft.description or existing.description
        existing.spec_json = draft.spec_json or existing.spec_json
        existing.scaffold_json = draft.scaffold_json or existing.scaffold_json
        existing.risk_level = draft.risk_level or existing.risk_level
        existing.status = INSTALLED_STATUS_INSTALLED
        existing.enabled = True
        existing.installed_at = now
        existing.updated_at = now

        version_row = _append_version(
            existing,
            action="upgrade",
            draft=draft,
            note=f"Upgraded from {old_version}",
        )
        db.add(version_row)

        draft.status = "installed"
        draft.installed_at = now
        await db.flush()
        return existing

    if existing is not None and existing.status in TERMINAL_STATUSES:
        log.warning(
            "[skill] finalize_install: a %s skill named '%s' already exists – "
            "cannot overwrite terminal state",
            existing.status,
            draft.name,
        )
        return None

    # ── Fresh install path ────────────────────────────────────────────────────
    log.info("[skill] installing new skill '%s' v1.0.0 from draft %s", draft.name, draft_id)
    skill = InstalledSkill(
        name=draft.name,
        description=draft.description or "",
        source_draft_id=draft_id,
        source_proposal_id=draft.proposal_id,
        current_version="1.0.0",
        rollback_version=None,
        status=INSTALLED_STATUS_INSTALLED,
        enabled=True,
        risk_level=draft.risk_level or "low",
        spec_json=draft.spec_json or {},
        scaffold_json=draft.scaffold_json or {},
        use_count=0,
        installed_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(skill)
    await db.flush()  # populate skill.id

    version_row = _append_version(skill, action="install", draft=draft)
    db.add(version_row)

    draft.status = "installed"
    draft.installed_at = now
    await db.flush()
    return skill


async def enable_skill(db: AsyncSession, skill_id: int) -> Optional[InstalledSkill]:
    """Enable a previously disabled skill."""
    result = await db.execute(select(InstalledSkill).where(InstalledSkill.id == skill_id))
    skill = result.scalar_one_or_none()
    if skill is None:
        return None
    if skill.status in TERMINAL_STATUSES:
        log.warning("[skill] enable: skill %s is in terminal state %s", skill_id, skill.status)
        return None

    skill.enabled = True
    skill.status = INSTALLED_STATUS_INSTALLED
    skill.updated_at = _now()

    db.add(_append_version(skill, action="enable"))
    await db.flush()
    return skill


async def disable_skill(db: AsyncSession, skill_id: int) -> Optional[InstalledSkill]:
    """Temporarily disable a skill (can be re-enabled)."""
    result = await db.execute(select(InstalledSkill).where(InstalledSkill.id == skill_id))
    skill = result.scalar_one_or_none()
    if skill is None:
        return None
    if skill.status in TERMINAL_STATUSES:
        log.warning("[skill] disable: skill %s is in terminal state %s", skill_id, skill.status)
        return None

    skill.enabled = False
    skill.status = INSTALLED_STATUS_DISABLED
    skill.updated_at = _now()

    db.add(_append_version(skill, action="disable"))
    await db.flush()
    return skill


async def revoke_skill(
    db: AsyncSession,
    skill_id: int,
    reason: str = "",
) -> Optional[InstalledSkill]:
    """
    Permanently deactivate a skill.  This is a terminal operation – the skill
    cannot be re-enabled and will never pass is_skill_executable().
    """
    result = await db.execute(select(InstalledSkill).where(InstalledSkill.id == skill_id))
    skill = result.scalar_one_or_none()
    if skill is None:
        return None
    if skill.status == INSTALLED_STATUS_REVOKED:
        return skill  # idempotent

    skill.enabled = False
    skill.status = INSTALLED_STATUS_REVOKED
    skill.revoke_reason = reason or "revoked"
    skill.updated_at = _now()

    db.add(_append_version(skill, action="revoke", note=skill.revoke_reason))
    await db.flush()
    return skill


async def rollback_skill(db: AsyncSession, skill_id: int) -> Optional[InstalledSkill]:
    """
    Roll back a skill to its previous version snapshot.

    Loads the most recent version row whose action == "install" or "upgrade"
    that is *before* the current version, restores spec/scaffold from it, and
    records a "rollback" version row.

    Returns None if there is no rollback target.
    """
    result = await db.execute(select(InstalledSkill).where(InstalledSkill.id == skill_id))
    skill = result.scalar_one_or_none()
    if skill is None:
        return None
    if skill.status in TERMINAL_STATUSES:
        log.warning("[skill] rollback: skill %s is in terminal state %s", skill_id, skill.status)
        return None
    if not skill.rollback_version:
        log.warning("[skill] rollback: skill %s has no rollback_version", skill_id)
        return None

    # Find the version row matching rollback_version
    target_version = skill.rollback_version
    ver_result = await db.execute(
        select(InstalledSkillVersion)
        .where(InstalledSkillVersion.skill_id == skill_id)
        .where(InstalledSkillVersion.version == target_version)
        .where(InstalledSkillVersion.action.in_(["install", "upgrade"]))
        .order_by(InstalledSkillVersion.id.desc())
    )
    target = ver_result.scalars().first()

    if target is None:
        log.warning(
            "[skill] rollback: no version snapshot found for skill %s @ %s",
            skill_id,
            target_version,
        )
        return None

    # Restore snapshot
    old_current = skill.current_version
    skill.current_version = target_version
    skill.rollback_version = ""  # type: ignore[assignment]  # no prior version to roll back to
    skill.spec_json = target.spec_json
    skill.scaffold_json = target.scaffold_json
    skill.risk_level = target.risk_level
    skill.source_draft_id = target.source_draft_id
    skill.status = INSTALLED_STATUS_INSTALLED
    skill.enabled = True
    skill.updated_at = _now()

    db.add(
        _append_version(
            skill,
            action="rollback",
            note=f"Rolled back from {old_current} to {target_version}",
        )
    )
    await db.flush()
    return skill


async def get_skill(db: AsyncSession, skill_id: int) -> Optional[InstalledSkill]:
    result = await db.execute(select(InstalledSkill).where(InstalledSkill.id == skill_id))
    return result.scalar_one_or_none()


async def get_skill_by_name(db: AsyncSession, name: str) -> Optional[InstalledSkill]:
    return await _find_by_name(db, name)


async def list_skills(
    db: AsyncSession,
    status: Optional[str] = None,
    limit: int = 100,
    profile_id: Optional[int] = None,
) -> List[InstalledSkill]:
    query = select(InstalledSkill).order_by(InstalledSkill.name)
    if status:
        query = query.where(InstalledSkill.status == status)
    if profile_id is not None:
        query = query.where(InstalledSkill.profile_id == profile_id)
    query = query.limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_version_history(
    db: AsyncSession,
    skill_id: int,
) -> List[InstalledSkillVersion]:
    result = await db.execute(
        select(InstalledSkillVersion)
        .where(InstalledSkillVersion.skill_id == skill_id)
        .order_by(InstalledSkillVersion.id.desc())
    )
    return list(result.scalars().all())


def is_skill_executable(skill: InstalledSkill) -> bool:
    """
    Safety gate.

    Returns True only when the skill is in 'installed' status AND enabled.
    Any other combination must block execution.
    """
    return skill.status == INSTALLED_STATUS_INSTALLED and skill.enabled is True
